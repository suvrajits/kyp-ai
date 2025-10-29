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


def embed_texts(texts):
    """Calls Azure OpenAI Embeddings API."""
    print(f"🧠 Embedding {len(texts)} chunks via Azure OpenAI...")
    response = client.embeddings.create(
        input=texts,
        model=settings.OPENAI_EMBEDDING_DEPLOYMENT,
    )
    vectors = np.array([d.embedding for d in response.data], dtype="float32")
    print(f"✅ Got embeddings of shape {vectors.shape}")
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
