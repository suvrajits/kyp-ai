# app/rag/vector_store_faiss.py

import os
import faiss
import numpy as np
import asyncio
from pathlib import Path
import tempfile
import shutil

# --------------------------------------------------------------------
# Base FAISS storage root
# --------------------------------------------------------------------
BASE_INDEX_DIR = Path("app/data/faiss_store")
BASE_INDEX_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------
# 🧠 Save FAISS index for a specific provider (async-safe)
# --------------------------------------------------------------------
def save_faiss_index(vectors: np.ndarray, chunks: list[str], doc_id: str, provider_dir: str):
    """
    Saves FAISS index and text chunks under the provider folder.
    Uses direct write (no tempfile) for Windows reliability.
    """
    provider_dir = Path(provider_dir)
    provider_dir.mkdir(parents=True, exist_ok=True)

    if vectors.ndim != 2:
        raise ValueError(f"Expected 2D embeddings array, got {vectors.shape}")

    dim = vectors.shape[1]
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    index_path = provider_dir / f"{doc_id}.index"
    chunk_path = provider_dir / f"{doc_id}_chunks.npy"

    try:
        # ✅ Write directly (atomicity handled by overwrite)
        faiss.write_index(index, str(index_path))
        np.save(str(chunk_path), np.array(chunks, dtype=object))
        print(f"💾 Saved FAISS index → {index_path} ({len(chunks)} chunks)")
    except Exception as e:
        print(f"❌ Error saving FAISS index for {doc_id}: {e}")



# --------------------------------------------------------------------
# 📂 Load a FAISS index and corresponding chunks
# --------------------------------------------------------------------
async def load_faiss_index(index_path: str, chunk_path: str):
    """
    Load a FAISS index and its corresponding text chunks asynchronously.
    """
    if not os.path.exists(index_path) or not os.path.exists(chunk_path):
        print(f"⚠️ Missing FAISS files: {index_path} or {chunk_path}")
        return None, None

    # Run blocking I/O in background thread
    def _load():
        index = faiss.read_index(index_path)
        chunks = np.load(chunk_path, allow_pickle=True)
        return index, chunks

    return await asyncio.to_thread(_load)


# --------------------------------------------------------------------
# 🔍 Query across all FAISS indices for a provider
# --------------------------------------------------------------------
def query_faiss_index(query_vec: np.ndarray, provider_dir: str, top_k: int = 3):
    """
    Search all documents in a provider’s FAISS namespace and
    return top-matching chunks by cosine similarity proxy.
    """
    provider_dir = Path(provider_dir)
    if not provider_dir.exists():
        print(f"⚠️ Provider directory not found: {provider_dir}")
        return []

    all_results = []
    faiss.normalize_L2(query_vec)

    # Collect all .index files under this provider
    for fname in os.listdir(provider_dir):
        if not fname.endswith(".index"):
            continue

        doc_id = fname.replace(".index", "")
        index_path = provider_dir / f"{doc_id}.index"
        chunk_path = provider_dir / f"{doc_id}_chunks.npy"

        index, chunks = asyncio.run(load_faiss_index(str(index_path), str(chunk_path)))
        if index is None or chunks is None:
            continue

        D, I = index.search(query_vec, top_k)
        for score, idx in zip(D[0], I[0]):
            if 0 <= idx < len(chunks):
                all_results.append({
                    "doc_id": doc_id,
                    "score": float(1 - score / 2),  # L2 distance → similarity proxy
                    "text": chunks[idx]
                })

    # Sort results by descending similarity
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


# --------------------------------------------------------------------
# 📊 Utility: List all providers and their indexed documents
# --------------------------------------------------------------------
def list_providers(base_dir: Path = BASE_INDEX_DIR):
    """
    Lists all providers with the number of indexed documents
    and document filenames.
    """
    providers = []
    if not base_dir.exists():
        return providers

    for provider_id in os.listdir(base_dir):
        provider_path = base_dir / provider_id
        if not provider_path.is_dir():
            continue

        docs = []
        for fname in os.listdir(provider_path):
            if fname.endswith(".index"):
                docs.append(fname.replace(".index", ""))

        providers.append({
            "provider_id": provider_id,
            "documents": docs,
            "doc_count": len(docs)
        })

    return providers
