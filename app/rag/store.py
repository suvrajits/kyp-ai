import os, pickle
import numpy as np
import faiss
from typing import List, Tuple

DATA_DIR = os.path.join("app", "data")
os.makedirs(DATA_DIR, exist_ok=True)
INDEX_PATH = os.path.join(DATA_DIR, "faiss_store.index")
META_PATH  = os.path.join(DATA_DIR, "meta.pkl")  # [(doc_id, chunk_text)]

def _new_index(dim: int) -> faiss.IndexFlatIP:
    index = faiss.IndexFlatIP(dim)  # cosine via normalized vectors
    return index

def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    return v / n

def load_store(dim: int) -> Tuple[faiss.IndexFlatIP, list]:
    if os.path.exists(INDEX_PATH) and os.path.exists(META_PATH):
        index = faiss.read_index(INDEX_PATH)
        with open(META_PATH, "rb") as f:
            meta = pickle.load(f)
        return index, meta
    # fresh
    index = _new_index(dim)
    meta = []
    return index, meta

def add_vectors(embeddings: np.ndarray, meta_rows: List[tuple], dim: int):
    index, meta = load_store(dim)
    # ensure shapes + normalize
    vectors = _normalize(embeddings.astype("float32"))
    if index.ntotal == 0 and index.d != vectors.shape[1]:
        # index was fresh; FAISS FlatIP has fixed d; rebuild to be safe
        index = _new_index(vectors.shape[1])
    index.add(vectors)
    meta.extend(meta_rows)
    # persist
    faiss.write_index(index, INDEX_PATH)
    with open(META_PATH, "wb") as f:
        pickle.dump(meta, f)

def search(query_vec: np.ndarray, top_k: int) -> List[tuple]:
    index, meta = load_store(query_vec.shape[1])
    if index.ntotal == 0:
        return []
    q = query_vec.astype("float32")
    q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)
    D, I = index.search(q, top_k)  # cosine similarity via IP on normalized
    hits = []
    for idx in I[0]:
        if idx == -1: 
            continue
        doc_id, chunk_text = meta[idx]
        hits.append((doc_id, chunk_text))
    return hits
