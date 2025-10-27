# app/rag/ask_api.py

import os
import numpy as np
import faiss
from fastapi import APIRouter
from openai import AzureOpenAI
from app.config import settings

# ------------------------------------------------------------
# Router setup
# ------------------------------------------------------------
router = APIRouter(tags=["RAG - Ask"], prefix="")  # No /rag prefix here

# ------------------------------------------------------------
# FAISS Index Directory
# ------------------------------------------------------------
INDEX_DIR = "app/data/faiss_store"

# ------------------------------------------------------------
# Helper: Load FAISS index and associated chunks
# ------------------------------------------------------------
def load_faiss_index(doc_id: str):
    """
    Loads a FAISS index and its corresponding chunk metadata.
    Returns (index, chunks) or (None, None) if not found.
    """
    index_path = os.path.join(INDEX_DIR, f"{doc_id}.index")
    chunk_path = os.path.join(INDEX_DIR, f"{doc_id}_chunks.npy")

    if not os.path.exists(index_path) or not os.path.exists(chunk_path):
        print(f"⚠️ No FAISS index found for {doc_id}")
        return None, None

    index = faiss.read_index(index_path)
    chunks = np.load(chunk_path, allow_pickle=True)
    return index, chunks


# ------------------------------------------------------------
# Helper: Search across all FAISS indices
# ------------------------------------------------------------
def search_faiss(query_vec, top_k=3):
    """
    Searches across all indexed documents in FAISS storage and
    returns the top K most relevant chunks with similarity scores.
    """
    all_results = []

    for fname in os.listdir(INDEX_DIR):
        if not fname.endswith(".index"):
            continue

        doc_id = fname.replace(".index", "")
        index, chunks = load_faiss_index(doc_id)
        if index is None:
            continue

        D, I = index.search(np.array([query_vec], dtype="float32"), top_k)
        for score, idx in zip(D[0], I[0]):
            if 0 <= idx < len(chunks):
                all_results.append({
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}#{idx}",
                    "score": float(1 - score / 2),  # Convert distance to similarity
                    "text": chunks[idx]
                })

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


# ------------------------------------------------------------
# Endpoint: Ask Documents (RAG Retrieval + GPT Answering)
# ------------------------------------------------------------
@router.post("/ask", summary="Ask Docs (RAG + GPT)", response_model=None)
def ask_docs(query: dict):
    """
    Endpoint to perform document-grounded Q&A using:
    1. FAISS vector search for relevant document chunks
    2. GPT-4o-mini for grounded natural language answers
    """
    question = query.get("query", "").strip()
    top_k = int(query.get("top_k", 3))

    if not question:
        return {"error": "❌ Missing query text."}

    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_key=settings.OPENAI_KEY,
        api_version=settings.OPENAI_API_VERSION,
        azure_endpoint=settings.OPENAI_ENDPOINT,
    )

    # Step 1: Embed user query
    print(f"🔍 Embedding user query: '{question}'")
    try:
        query_emb = client.embeddings.create(
            input=question,
            model=settings.OPENAI_EMBEDDING_DEPLOYMENT
        ).data[0].embedding
    except Exception as e:
        return {"error": f"❌ Failed to embed query: {str(e)}"}

    # Step 2: Search FAISS index
    results = search_faiss(query_emb, top_k=top_k)
    if not results:
        return {"answer": "No documents indexed yet.", "sources": [], "context_preview": []}

    # Step 3: Build GPT context
    context_text = "\n".join([r["text"] for r in results])
    context_preview = [
        {"chunk_id": r["chunk_id"], "score": r["score"], "preview": r["text"][:200]}
        for r in results
    ]

    # Step 4: Ask GPT model
    print(f"💬 Sending {len(results)} context chunks to GPT-4o-mini...")
    try:
        completion = client.chat.completions.create(
            model=settings.OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are an AI assistant that answers strictly based on uploaded documents."},
                {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {question}"}
            ],
            temperature=0.2,
        )
        answer = completion.choices[0].message.content.strip()
        print("✅ Answer generated successfully.")
    except Exception as e:
        return {"error": f"❌ GPT-4o-mini request failed: {str(e)}"}

    # Step 5: Return structured response
    return {
        "answer": answer,
        "sources": [{"chunk_id": r["chunk_id"], "score": r["score"]} for r in results],
        "context_preview": context_preview
    }
