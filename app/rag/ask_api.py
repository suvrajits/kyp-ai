# app/rag/ask_api.py

import os
import numpy as np
import faiss
from pathlib import Path
from fastapi import APIRouter, Request
from openai import AzureOpenAI
from app.config import settings
import glob

router = APIRouter(tags=["RAG - Ask"], prefix="")  # No /rag prefix here

# ------------------------------------------------------------
# FAISS Index Directory
# ------------------------------------------------------------
INDEX_DIR = Path("app/data/faiss_store")
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# Helper: Load FAISS index and chunks
# ------------------------------------------------------------
import glob

def load_faiss_index(doc_id: str):
    index_path = os.path.join(INDEX_DIR, f"{doc_id}.index")
    chunk_path = os.path.join(INDEX_DIR, f"{doc_id}_chunks.npy")

    # 🔍 Search recursively if not found
    if not os.path.exists(index_path) or not os.path.exists(chunk_path):
        matches = glob.glob(os.path.join(INDEX_DIR, "**", f"{doc_id}.index"), recursive=True)
        if matches:
            index_path = matches[0]
            chunk_path = index_path.replace(".index", "_chunks.npy")
            print(f"✅ Found FAISS index for {doc_id} at {index_path}")
        else:
            print(f"⚠️ No FAISS index found for {doc_id}")
            return None, None

    index = faiss.read_index(index_path)
    chunks = np.load(chunk_path, allow_pickle=True)
    return index, chunks




# ------------------------------------------------------------
# Helper: Search within one FAISS store
# ------------------------------------------------------------
def search_index(index, chunks, query_vec, doc_id, top_k=3):
    D, I = index.search(np.array([query_vec], dtype="float32"), top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if 0 <= idx < len(chunks):
            results.append({
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}#{idx}",
                "score": float(1 - score / 2),  # distance → similarity
                "text": chunks[idx],
            })
    return results


# ------------------------------------------------------------
# Helper: Search across all FAISS indices (fallback)
# ------------------------------------------------------------
def global_search(query_vec, top_k=3):
    all_results = []
    for fname in os.listdir(INDEX_DIR):
        if not fname.endswith(".index"):
            continue
        doc_id = fname.replace(".index", "")
        index_path = INDEX_DIR / fname
        chunk_path = INDEX_DIR / f"{doc_id}_chunks.npy"
        index, chunks = load_faiss_index(index_path, chunk_path)
        if not index:
            continue
        all_results.extend(search_index(index, chunks, query_vec, doc_id, top_k))
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


# ------------------------------------------------------------
# Endpoint: Ask (RAG + GPT)
# ------------------------------------------------------------
@router.post("/ask", summary="Ask Documents (RAG + GPT)")
async def ask_docs(query: dict, request: Request = None):
    """
    Document-grounded Q&A using:
      1. Risk-aware FAISS retrieval (if query mentions risk)
      2. GPT-4o-mini for grounded, explainable answers
    """
    question = query.get("query", "").strip()
    provider_id = query.get("provider_id", "").strip()
    top_k = int(query.get("top_k", 3))

    if not question:
        return {"error": "❌ Missing query text."}

    print(f"🔍 Received query: '{question}' (provider={provider_id or 'global'})")

    # Initialize OpenAI client
    client = AzureOpenAI(
        api_key=settings.OPENAI_KEY,
        api_version=settings.OPENAI_API_VERSION,
        azure_endpoint=settings.OPENAI_ENDPOINT,
    )

    # Step 1️⃣ Embed query
    try:
        query_emb = client.embeddings.create(
            input=question,
            model=settings.OPENAI_EMBEDDING_DEPLOYMENT
        ).data[0].embedding
    except Exception as e:
        return {"error": f"❌ Failed to embed query: {str(e)}"}

    query_lower = question.lower()
    results = []

    # Step 2️⃣ Try risk-specific FAISS index first (if applicable)
    if provider_id:
        provider_dir = INDEX_DIR / provider_id
        risk_index = provider_dir / "index.faiss"
        chunk_path = provider_dir / "chunks.npy"

        if any(k in query_lower for k in ["risk", "score", "breakdown", "category", "compliance", "explain"]):
            if risk_index.exists() and chunk_path.exists():
                print(f"🧠 Searching risk FAISS for provider {provider_id}...")
                index, chunks = load_faiss_index(risk_index, chunk_path)
                if index:
                    results = search_index(index, chunks, query_emb, provider_id, top_k)
                    print(f"✅ Retrieved {len(results)} risk chunks from provider {provider_id}")
            else:
                print(f"⚠️ No dedicated risk FAISS found for {provider_id}, falling back to global search.")

    # Step 3️⃣ Fallback to global search if risk index empty or not found
    if not results:
        print("🌐 Performing global FAISS search...")
        results = global_search(query_emb, top_k=top_k)

    if not results:
        return {"answer": "⚠️ No relevant context found.", "sources": [], "context_preview": []}

    # Step 4️⃣ Build GPT context
    context_text = "\n\n---\n\n".join([r["text"] for r in results])
    context_preview = [
        {"chunk_id": r["chunk_id"], "score": r["score"], "preview": r["text"][:200]}
        for r in results
    ]

    # Step 5️⃣ Ask GPT with grounded context
    print(f"💬 Sending {len(results)} context chunks to GPT...")
    try:
        completion = client.chat.completions.create(
            model=settings.OPENAI_CHAT_DEPLOYMENT,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a specialized AI risk analyst. "
                        "Answer **only** using the provided context from risk intelligence data and documents. "
                        "If the context does not include relevant data, clearly state that."
                    )
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context_text}\n\nQuestion: {question}"
                }
            ],
        )
        answer = completion.choices[0].message.content.strip()
        print("✅ Answer generated successfully.")
    except Exception as e:
        return {"error": f"❌ GPT request failed: {str(e)}"}

    # Step 6️⃣ Return structured response
    return {
        "answer": answer,
        "sources": [{"chunk_id": r["chunk_id"], "score": r["score"]} for r in results],
        "context_preview": context_preview
    }

