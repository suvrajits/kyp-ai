# app/rag/ingest_utils.py

import os
import time
import numpy as np
import faiss
from pathlib import Path
from openai import AzureOpenAI
from app.config import settings

# Try both PyPDF2 and PyMuPDF
try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


# ------------------------------------------
# 📄 Extract text from PDF (fallback safe)
# ------------------------------------------
def extract_text_from_pdf(path: str) -> str:
    print(f"⚙️ Extracting text from PDF: {path}")
    text = ""

    if HAS_PYPDF2:
        try:
            reader = PdfReader(path)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        except Exception as e:
            print("❌ PyPDF2 failed:", e)

    # fallback if PyPDF2 empty or failed
    if not text and HAS_PYMUPDF:
        try:
            doc = fitz.open(path)
            text = "\n".join(page.get_text("text") for page in doc)
        except Exception as e:
            print("❌ PyMuPDF failed:", e)

    if not text:
        raise ValueError("Failed to extract any text from the PDF.")
    return text


# ------------------------------------------
# ✂️ Split text into chunks
# ------------------------------------------
def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50):
    print("✂️ Splitting text into chunks...")
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    print(f"✅ Created {len(chunks)} chunks.")
    return chunks


# ------------------------------------------
# 🧠 Generate embeddings via Azure OpenAI
# ------------------------------------------
def embed_texts(chunks, batch_size=10):
    print(f"🔌 Initializing AzureOpenAI client for {len(chunks)} chunks...")
    client = AzureOpenAI(
        api_key=settings.OPENAI_KEY,
        api_version=settings.OPENAI_API_VERSION,
        azure_endpoint=settings.OPENAI_ENDPOINT,
        timeout=45.0,
    )

    vectors = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        print(f"📡 Embedding batch {i // batch_size + 1} / {len(chunks) // batch_size + 1}")
        try:
            response = client.embeddings.create(
                input=batch,
                model=settings.OPENAI_EMBEDDING_DEPLOYMENT,
            )
            vectors.extend([r.embedding for r in response.data])
        except Exception as e:
            print("❌ Batch failed:", e)
            continue

    return np.array(vectors, dtype="float32")

# ------------------------------------------
# 💾 Save FAISS index
# ------------------------------------------
def save_faiss_index(vectors, file_path):
    print("💾 Saving FAISS index...")
    index = faiss.IndexFlatL2(vectors.shape[1])
    index.add(vectors)
    os.makedirs("app/vector_store", exist_ok=True)

    index_file = f"app/vector_store/{Path(file_path).stem}.faiss"
    faiss.write_index(index, index_file)
    print(f"✅ FAISS index saved at {index_file}")


# ------------------------------------------
# 🔍 Search FAISS index
# ------------------------------------------
def search(query_vec, top_k=4):
    print("🔍 Performing vector search...")
    vector_store_path = "app/vector_store"
    files = [f for f in os.listdir(vector_store_path) if f.endswith(".faiss")]
    if not files:
        print("⚠️ No FAISS index files found.")
        return []

    index_path = os.path.join(vector_store_path, files[0])
    index = faiss.read_index(index_path)

    distances, indices = index.search(query_vec, top_k)
    return list(zip(indices[0], distances[0]))


# ------------------------------------------
# 🚀 Main ingestion pipeline
# ------------------------------------------
def ingest_document(file_path):
    print("⚙️ Starting ingestion for:", file_path)

    text = extract_text_from_pdf(file_path)
    print("📄 Text extracted length:", len(text))

    chunks = chunk_text(text)
    print("✂️ Chunked into:", len(chunks), "pieces")

    print("🧠 Starting embeddings call...")
    vectors = embed_texts(chunks)
    print("✅ Embeddings completed. Shape:", vectors.shape)

    save_faiss_index(vectors, file_path)
    print("💾 FAISS index saved successfully.")

    total_tokens = sum(len(c.split()) for c in chunks)
    print(f"📊 Ingestion complete: {len(chunks)} chunks, {total_tokens} tokens")

    return {
        "doc_id": Path(file_path).stem,
        "chunks": len(chunks),
        "tokens": total_tokens,
    }
