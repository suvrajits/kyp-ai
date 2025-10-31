# app/services/faiss_utils.py
from __future__ import annotations
import faiss
import os, json
import numpy as np

def create_faiss_index(dim: int) -> faiss.IndexFlatIP:
    """
    Creates a FAISS index for L2-normalized cosine similarity.
    """
    return faiss.IndexFlatIP(dim)


def save_faiss_index(index: faiss.IndexFlatIP, metadata: list[dict], folder_path: str):
    """
    Saves FAISS index and associated metadata JSON.
    """
    os.makedirs(folder_path, exist_ok=True)
    faiss.write_index(index, os.path.join(folder_path, "index.faiss"))
    with open(os.path.join(folder_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def load_faiss_index(index_path: str, meta_path: str):
    """
    Loads a FAISS index and associated metadata.
    """
    index = faiss.read_index(index_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return index, metadata


def append_to_faiss_index(index_path: str, meta_path: str, new_vectors: np.ndarray, new_metadata: list[dict]):
    """
    Loads an existing FAISS index, appends new vectors + metadata, and saves.
    """
    if not os.path.exists(index_path):
        # Create a new one if not found
        index = create_faiss_index(new_vectors.shape[1])
        metadata = []
    else:
        index, metadata = load_faiss_index(index_path, meta_path)

    index.add(new_vectors)
    metadata.extend(new_metadata)
    save_faiss_index(index, metadata, os.path.dirname(index_path))
    return index, metadata
