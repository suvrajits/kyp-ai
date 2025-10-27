# app/rag/vector_store_faiss.py

import os
import faiss
import numpy as np

INDEX_DIR = "app/data/faiss_store"
os.makedirs(INDEX_DIR, exist_ok=True)

def save_faiss_index(vectors: np.ndarray, doc_id: str, chunks: list[str]):
    """Save FAISS index and chunk data for later retrieval."""
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    index_path = os.path.join(INDEX_DIR, f"{doc_id}.index")
    chunk_path = os.path.join(INDEX_DIR, f"{doc_id}_chunks.npy")

    faiss.write_index(index, index_path)
    np.save(chunk_path, np.array(chunks, dtype=object))

    print(f"💾 Saved FAISS index → {index_path}  ({len(chunks)} chunks)")

def load_faiss_index(doc_id: str):
    """Load FAISS index and chunks."""
    index_path = os.path.join(INDEX_DIR, f"{doc_id}.index")
    chunk_path = os.path.join(INDEX_DIR, f"{doc_id}_chunks.npy")

    if not os.path.exists(index_path) or not os.path.exists(chunk_path):
        print(f"⚠️ No FAISS index found for {doc_id}")
        return None, None

    index = faiss.read_index(index_path)
    chunks = np.load(chunk_path, allow_pickle=True)
    return index, chunks

def query_faiss_index(query_vec: np.ndarray, doc_id: str, top_k: int = 3):
    """Query FAISS index and return top chunks."""
    index, chunks = load_faiss_index(doc_id)
    if index is None:
        return []

    D, I = index.search(np.array([query_vec], dtype="float32"), top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if 0 <= idx < len(chunks):
            results.append({
                "score": float(1 - score / 2),
                "text": chunks[idx],
            })
    return results
