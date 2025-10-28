# app/rag/ingest.py

import os
import re
import uuid
import numpy as np
from PyPDF2 import PdfReader
import fitz  # PyMuPDF
from openai import AzureOpenAI
from app.config import settings
from app.rag.vector_store_faiss import save_faiss_index  # ✅ centralized FAISS handler
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

# ============================================================
# Embedding + FAISS persistence (delegated)
# ============================================================
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
def ingest_pdf(file_path: str, provider_id: str, doc_name: str = None):
    """
    Reads a PDF, splits it into chunks, creates embeddings,
    and saves them into a provider-specific FAISS directory.

    Args:
        file_path: str - full path to PDF file.
        provider_id: str - Application ID (FAISS namespace).
        doc_name: str - optional friendly document name.

    Returns:
        tuple[list[str], int]: (chunks, total_token_count)
    """
    print(f"🚀 Starting ingestion for provider: {provider_id}")
    all_chunks = []
    token_count = 0

    # Create a unique document ID to prevent overwrites
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", doc_name or Path(file_path).stem)
    doc_id = f"{safe_name}_{uuid.uuid4().hex[:6]}"

    try:
        # Extract & chunk PDF text
        for i, page_text in enumerate(extract_text_generator(file_path)):
            if not page_text.strip():
                continue

            print(f"📄 Processing page {i+1}")
            chunks = chunk_text_streaming([page_text])
            all_chunks.extend(chunks)
            token_count += len(page_text.split())

        print(f"✅ Total chunks created: {len(all_chunks)}, Tokens: {token_count}")

        # Embed & save FAISS index
        if all_chunks:
            vectors = embed_texts(all_chunks)

            # ✅ Normalize vectors for cosine-like similarity
            faiss.normalize_L2(vectors)

            provider_dir = Path("app/data/faiss_store") / provider_id
            provider_dir.mkdir(parents=True, exist_ok=True)

            save_faiss_index(
                vectors=vectors,
                chunks=all_chunks,
                doc_id=doc_id,
                provider_dir=str(provider_dir)
            )

            print(f"💾 Saved FAISS index for {doc_id} under {provider_id}")
        else:
            print("⚠️ No valid chunks extracted; skipping embedding.")

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
