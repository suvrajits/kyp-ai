# app/rag/ingest.py

import os
import re
import uuid
import numpy as np
from PyPDF2 import PdfReader
import fitz  # PyMuPDF
from openai import AzureOpenAI
from app.config import settings
from app.rag.vector_store_faiss import save_faiss_index, load_faiss_index
from pathlib import Path
import faiss  # ✅ for L2 normalization

# ============================================================
# Azure OpenAI Client
# ============================================================
client = AzureOpenAI(
    api_key=settings.OPENAI_KEY,
    api_version=settings.OPENAI_API_VERSION,
    azure_endpoint=settings.OPENAI_ENDPOINT,
)

EMBEDDING_DIM = 1536  # consistent with text-embedding-3-small / Ada v2

# ============================================================
# Utility functions
# ============================================================
def clean_text(t: str) -> str:
    """Cleans up extra whitespace and newline clutter."""
    return re.sub(r"\s+", " ", t).strip()


def chunk_text_streaming(page_texts, chunk_size=800, overlap=100):
    """Splits long text into overlapping chunks for embeddings."""
    chunks = []
    for page_text in page_texts:
        text = clean_text(page_text)
        if not text:
            continue
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += chunk_size - overlap
    return chunks


def extract_text_generator(file_path: str):
    """Yields text per page using PyMuPDF, fallback to PyPDF2."""
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                yield page.get_text("text")
    except Exception as e:
        print(f"⚠️ PyMuPDF failed: {e}. Falling back to PyPDF2.")
        reader = PdfReader(file_path)
        for page in reader.pages:
            yield page.extract_text() or ""


def embed_texts(texts, batch_size: int = 20):
    """
    Calls Azure OpenAI Embeddings API in safe batches.
    Used by both PDF ingestion and risk orchestrator (for watchlist embeddings).
    """
    import time
    if not texts:
        print("⚠️ embed_texts() called with empty input.")
        return np.zeros((0, 1536), dtype="float32")

    all_vectors = []
    total = len(texts)
    print(f"🧠 Embedding {total} text chunk(s) via Azure OpenAI (batch size={batch_size})...")

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        try:
            response = client.embeddings.create(
                input=batch,
                model=settings.OPENAI_EMBEDDING_DEPLOYMENT,
            )
            batch_vectors = [d.embedding for d in response.data]
            all_vectors.extend(batch_vectors)
            print(f"✅ Embedded batch {i // batch_size + 1} ({len(batch_vectors)} items)")
        except Exception as e:
            print(f"❌ Embedding failed for batch {i // batch_size + 1}: {e}")
            # Fill failed batch with zero vectors of correct shape to avoid breaking
            all_vectors.extend([[0.0] * 1536 for _ in batch])
            time.sleep(2)  # backoff

    vectors = np.array(all_vectors, dtype="float32")
    print(f"✅ All embeddings complete. Final shape: {vectors.shape}")
    return vectors


# ============================================================
# Main entrypoint (per-provider multi-doc ingestion)
# ============================================================
def ingest_pdf(file_path: str, provider_id: str, doc_name: str = None, append: bool = True):
    """
    Reads a PDF, splits it into chunks, creates embeddings,
    and saves or merges them into a provider-specific FAISS directory.

    Args:
        file_path: str - full path to PDF file.
        provider_id: str - Application ID (FAISS namespace).
        doc_name: str - optional friendly document name.
        append: bool - if True, merges with existing FAISS index.

    Returns:
        tuple[list[str], int]: (chunks, total_token_count)
    """
    print(f"🚀 Starting ingestion for provider: {provider_id} ({'append' if append else 'overwrite'})")
    all_chunks = []
    token_count = 0

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", doc_name or Path(file_path).stem)
    doc_id = f"{safe_name}_{uuid.uuid4().hex[:6]}"

    try:
        # Step 1️⃣ Extract and chunk PDF
        for i, page_text in enumerate(extract_text_generator(file_path)):
            if not page_text.strip():
                continue

            print(f"📄 Processing page {i + 1}")
            chunks = chunk_text_streaming([page_text])
            enriched_chunks = [
                f"Document: {Path(file_path).name} | Page: {i + 1}\n\n{text}"
                for text in chunks
            ]
            all_chunks.extend(enriched_chunks)
            token_count += len(page_text.split())

        print(f"✅ Total chunks created: {len(all_chunks)}, Tokens: {token_count}")

        if not all_chunks:
            print("⚠️ No valid chunks extracted; skipping embedding.")
            return [], token_count

        # Step 2️⃣ Embed new text chunks
        new_vectors = embed_texts(all_chunks)
        faiss.normalize_L2(new_vectors)

        provider_dir = Path("app/data/faiss_store") / provider_id
        provider_dir.mkdir(parents=True, exist_ok=True)

        # Step 3️⃣ Merge with existing FAISS data if append=True
        existing_vectors, existing_chunks = None, []
        if append:
            try:
                existing_vectors, existing_chunks = load_faiss_index(str(provider_dir))
                if existing_vectors is not None:
                    print(f"🔁 Merging {len(existing_vectors)} existing vectors with {len(new_vectors)} new ones...")
                    all_chunks = existing_chunks + all_chunks
                    new_vectors = np.concatenate([existing_vectors, new_vectors], axis=0)
            except Exception as e:
                print(f"⚠️ No existing FAISS index found or failed to load: {e}")

        # Step 4️⃣ Save combined FAISS data
        save_faiss_index(
            vectors=new_vectors,
            chunks=all_chunks,
            doc_id=provider_id,  # Use provider_id as global key
            provider_dir=str(provider_dir)
        )
        print(f"💾 Saved FAISS index for {provider_id} ({len(all_chunks)} chunks total)")

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")

    finally:
        try:
            os.remove(file_path)
        except PermissionError:
            print(f"⚠️ Could not delete file {file_path}, skipping cleanup.")
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

    return all_chunks, token_count

def ingest_text_block(provider_id: str, text_block: str, doc_name: str = "risk_summary", append: bool = True):
    """
    Ingests a text block (risk summary or any generated narrative) into provider's FAISS index.
    """
    from app.rag.vector_store_faiss import save_faiss_index, load_faiss_index
    import faiss

    print(f"🧠 Ingesting text block for provider {provider_id} ({'append' if append else 'overwrite'})")

    text_block = clean_text(text_block)
    chunks = chunk_text_streaming([text_block], chunk_size=800, overlap=100)
    enriched_chunks = [f"[{doc_name}] {c}" for c in chunks]

    if not enriched_chunks:
        print("⚠️ No valid text chunks to embed — skipping.")
        return 0

    vectors = embed_texts(enriched_chunks)
    faiss.normalize_L2(vectors)

    provider_dir = Path("app/data/faiss_store") / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    if append:
        try:
            existing_vectors, existing_chunks = load_faiss_index(provider_id)  # ✅ fixed here
            if existing_vectors is not None:
                print(f"🔁 Merging {len(existing_vectors)} existing vectors with {len(vectors)} new ones...")
                vectors = np.concatenate([existing_vectors, vectors], axis=0)
                enriched_chunks = existing_chunks + enriched_chunks
        except Exception as e:
            print(f"⚠️ Could not load existing FAISS for {provider_id}: {e}")

    save_faiss_index(vectors=vectors, chunks=enriched_chunks, doc_id=provider_id, provider_dir=str(provider_dir))
    print(f"💾 Embedded text block for provider {provider_id} ({len(enriched_chunks)} chunks).")

    return len(enriched_chunks)
