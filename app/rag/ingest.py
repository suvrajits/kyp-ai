# app/rag/ingest.py

import os
import re
import numpy as np
from PyPDF2 import PdfReader
import fitz  # PyMuPDF
from openai import AzureOpenAI
from app.config import settings
from app.rag.vector_store_faiss import save_faiss_index  # ✅ central FAISS handler

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
# Main entrypoint
# ============================================================
def ingest_pdf(file_path: str, doc_id="provider_guidelines"):
    """
    Reads a PDF, splits it into chunks, creates embeddings,
    and saves them into FAISS for later RAG querying.

    Returns:
        tuple[list[str], int]: (chunks, total_token_count)
    """
    print(f"🚀 Starting ingestion for: {file_path}")
    all_chunks = []
    token_count = 0

    try:
        for i, page_text in enumerate(extract_text_generator(file_path)):
            if not page_text.strip():
                continue

            print(f"📄 Processing page {i+1}")
            chunks = chunk_text_streaming([page_text])
            all_chunks.extend(chunks)
            token_count += len(page_text.split())

        print(f"✅ Total chunks created: {len(all_chunks)}, Tokens: {token_count}")

        if all_chunks:
            vectors = embed_texts(all_chunks)
            save_faiss_index(vectors=vectors, doc_id=doc_id, chunks=all_chunks)  # ✅ centralized call
        else:
            print("⚠️ No valid chunks extracted; skipping embedding.")

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")

    return all_chunks, token_count