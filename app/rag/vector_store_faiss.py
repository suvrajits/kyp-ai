import os
import faiss
import numpy as np
import asyncio
from pathlib import Path
import json

# --------------------------------------------------------------------
# Base FAISS storage root
# --------------------------------------------------------------------
BASE_INDEX_DIR = Path("app/data/faiss_store")
BASE_INDEX_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------
# 🧠 Save FAISS index for a specific provider
# --------------------------------------------------------------------
def save_faiss_index(vectors: np.ndarray, chunks: list[str], doc_id: str, provider_dir: str):
    """
    Saves FAISS index and text chunks under the provider folder.
    Uses direct write for atomic updates.
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
        faiss.write_index(index, str(index_path))
        np.save(str(chunk_path), np.array(chunks, dtype=object))
        print(f"💾 Saved FAISS index → {index_path} ({len(chunks)} chunks)")
    except Exception as e:
        print(f"❌ Error saving FAISS index for {doc_id}: {e}")


# --------------------------------------------------------------------
# 📂 Load FAISS index (sync, recursive search)
# --------------------------------------------------------------------
def load_faiss_index(doc_id: str):
    """
    Loads FAISS index and chunks for a given provider or doc ID.
    Searches recursively if not found in the top level.
    """
    import glob

    # Default paths
    index_path = BASE_INDEX_DIR / f"{doc_id}.index"
    chunk_path = BASE_INDEX_DIR / f"{doc_id}_chunks.npy"

    # 🔍 If not found, search recursively (handles risk subfolders)
    if not index_path.exists() or not chunk_path.exists():
        matches = glob.glob(str(BASE_INDEX_DIR / "**" / f"{doc_id}.index"), recursive=True)
        if matches:
            index_path = Path(matches[0])
            chunk_path = index_path.with_name(index_path.stem + "_chunks.npy")
            print(f"✅ Found FAISS index for {doc_id} → {index_path}")
        else:
            print(f"⚠️ No FAISS index found for {doc_id}")
            return None, None

    try:
        index = faiss.read_index(str(index_path))
        chunks = np.load(str(chunk_path), allow_pickle=True)
        return index, chunks
    except Exception as e:
        print(f"❌ Failed to load FAISS for {doc_id}: {e}")
        return None, None


# --------------------------------------------------------------------
# 🔍 Async loader variant (for RAG pipelines if needed)
# --------------------------------------------------------------------
async def load_faiss_index_async(doc_id: str):
    """Async wrapper for load_faiss_index()."""
    return await asyncio.to_thread(load_faiss_index, doc_id)


# --------------------------------------------------------------------
# 🔍 Query across all FAISS indices for a provider
# --------------------------------------------------------------------
def query_faiss_index(query_vec: np.ndarray, provider_dir: str, top_k: int = 3):
    """
    Search all FAISS documents in a provider’s directory.
    """
    provider_dir = Path(provider_dir)
    if not provider_dir.exists():
        print(f"⚠️ Provider directory not found: {provider_dir}")
        return []

    all_results = []
    faiss.normalize_L2(query_vec)

    for fname in os.listdir(provider_dir):
        if not fname.endswith(".index"):
            continue

        doc_id = fname.replace(".index", "")
        index_path = provider_dir / f"{doc_id}.index"
        chunk_path = provider_dir / f"{doc_id}_chunks.npy"

        index, chunks = load_faiss_index(doc_id)
        if index is None or chunks is None:
            continue

        D, I = index.search(query_vec, top_k)
        for score, idx in zip(D[0], I[0]):
            if 0 <= idx < len(chunks):
                all_results.append({
                    "doc_id": doc_id,
                    "score": float(1 - score / 2),
                    "text": chunks[idx]
                })

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


# --------------------------------------------------------------------
# 📊 Utility: List all providers and their indexed documents
# --------------------------------------------------------------------
def list_providers(base_dir: Path = BASE_INDEX_DIR):
    """
    Lists all providers and their indexed FAISS files.
    """
    providers = []
    if not base_dir.exists():
        return providers

    for provider_id in os.listdir(base_dir):
        provider_path = base_dir / provider_id
        if not provider_path.is_dir():
            continue

        docs = [f.replace(".index", "") for f in os.listdir(provider_path) if f.endswith(".index")]
        providers.append({
            "provider_id": provider_id,
            "documents": docs,
            "doc_count": len(docs)
        })

    return providers


def inspect_index(provider_id: str, verbose: bool = False):
    """
    Returns diagnostic info for provider FAISS store.
    """
    base_dir = f"app/data/faiss_store/{provider_id}"
    index_path = os.path.join(base_dir, f"{provider_id}.index")
    chunk_path = os.path.join(base_dir, f"{provider_id}_chunks.npy")

    if not os.path.exists(index_path):
        raise FileNotFoundError(f"Index file not found: {index_path}")

    index = faiss.read_index(index_path)
    n_vectors = index.ntotal

    summary = {
        "index_file": index_path,
        "chunk_file": os.path.exists(chunk_path),
        "vector_count": n_vectors
    }

    if verbose and os.path.exists(chunk_path):
        chunks = np.load(chunk_path, allow_pickle=True).tolist()
        summary["preview"] = chunks[:3]  # first 3 text snippets

    return summary