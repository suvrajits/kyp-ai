# app/rag/router.py

from fastapi import APIRouter, UploadFile, File
import tempfile, os
from app.rag.ingest import ingest_pdf
from app.rag.vector_store_faiss import load_faiss_index
from app.config import settings
from openai import AzureOpenAI
import numpy as np

router = APIRouter(tags=["RAG - Ingest & Ask"])


# ============================================================
# 1️⃣ PDF Ingestion Endpoint
# ============================================================
@router.post("/ingest", summary="Ingest PDF into FAISS index")
async def ingest(file: UploadFile = File(...)):
    """
    Upload and ingest a PDF file.
    - Extracts text
    - Chunks it
    - Embeds via Azure OpenAI
    - Saves FAISS index via ingest_pdf()
    """
    # Windows-safe temp handling
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        temp_path = tmp.name

    try:
        chunks, tokens = ingest_pdf(temp_path)  # ✅ Handles FAISS saving internally
        print("✅ Ingestion complete via ingest_pdf().")

        return {
            "doc_id": "provider_guidelines",
            "chunks": len(chunks),
            "tokens": tokens,
            "status": "✅ FAISS index created successfully.",
        }

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")
        return {"error": str(e)}

    finally:
        try:
            os.remove(temp_path)
        except PermissionError:
            print(f"⚠️ Could not delete temp file {temp_path}, skipping cleanup.")


# ============================================================
# 2️⃣ Simple Ask Endpoint (FAISS + GPT)
# ============================================================
@router.post("/ask")
def ask(req: dict):
    """
    Ask a question against the last ingested FAISS index.
    Uses embedding similarity + GPT answer synthesis.
    """
    query = req.get("query", "")
    if not query:
        return {"error": "Missing query text."}

    top_k = req.get("top_k", 3)
    doc_id = req.get("doc_id", "provider_guidelines")

    client = AzureOpenAI(
        api_key=settings.OPENAI_KEY,
        api_version=settings.OPENAI_API_VERSION,
        azure_endpoint=settings.OPENAI_ENDPOINT,
    )

    # 1️⃣ Embed the query
    print(f"🔍 Embedding query: {query}")
    qvec = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_DEPLOYMENT,
        input=query
    ).data[0].embedding

    # 2️⃣ Retrieve similar chunks
    index, chunks = load_faiss_index(doc_id)
    if index is None:
        return {"error": f"No FAISS index found for {doc_id}"}

    D, I = index.search(np.array([qvec], dtype="float32"), top_k)
    matched_chunks = [chunks[i] for i in I[0] if i < len(chunks)]

    if not matched_chunks:
        return {"answer": "No relevant documents found.", "sources": [], "context_preview": []}

    # 3️⃣ Create context string
    context = "\n\n".join(matched_chunks)
    preview = [{"chunk_id": i, "text": c[:150]} for i, c in enumerate(matched_chunks)]

    # 4️⃣ Ask GPT using context
    print(f"💬 Sending top {len(matched_chunks)} chunks to GPT-4o-mini...")
    prompt = (
        "You are an expert assistant that answers strictly based on the provided context. "
        "If the answer isn't found in the context, respond: 'I don't have that information.'\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        "Answer:"
    )

    completion = client.chat.completions.create(
        model=settings.OPENAI_CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content.strip()
    print("✅ Answer generated successfully.")

    return {
        "answer": answer,
        "sources": [f"{doc_id}#{i}" for i in I[0].tolist()],
        "context_preview": preview,
    }
