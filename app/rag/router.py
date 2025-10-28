# app/rag/router.py

from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pathlib import Path
import tempfile, os, asyncio, json
from datetime import datetime
import numpy as np
from openai import AzureOpenAI

from app.rag.ingest import ingest_pdf
from app.config import settings
from app.rag.vector_store_faiss import query_faiss_index

router = APIRouter(tags=["RAG - Ingest & Ask (Per Provider)"])

# ============================================================
# 1️⃣ Upload & Ingest Multiple Documents (Dashboard)
# ============================================================
@router.post("/{provider_id}/ingest", summary="Upload & Ingest documents for a specific provider")
async def upload_and_ingest_for_dashboard(
    request: Request,
    provider_id: str,
    files: list[UploadFile] = File(...),
):
    """
    Upload and embed multiple PDFs for a provider.
    Also records filenames in applications.json and builds FAISS indexes.
    """
    try:
        provider_dir = Path("app/data/faiss_store") / provider_id
        provider_dir.mkdir(parents=True, exist_ok=True)

        apps_file = Path("app/data/applications.json")
        apps = json.loads(apps_file.read_text()) if apps_file.exists() else []

        record = next((r for r in apps if r["id"] == provider_id), None)
        if not record:
            return JSONResponse(status_code=404, content={"error": f"Provider {provider_id} not found."})

        record.setdefault("documents", [])

        for file in files:
            file_path = provider_dir / file.filename
            with open(file_path, "wb") as f:
                f.write(await file.read())
            print(f"📥 Saved {file.filename} to {file_path}")

            # Run embedding + FAISS in background thread
            await asyncio.to_thread(
                ingest_pdf,
                str(file_path),
                provider_id=provider_id,
                doc_name=file.filename,
            )

            # Record metadata
            record["documents"].append({
                "filename": file.filename,
                "uploaded_at": datetime.now().isoformat(),
            })

        apps_file.write_text(json.dumps(apps, indent=2))
        print(f"✅ Ingested {len(files)} file(s) for provider {provider_id}")

        return RedirectResponse(url=f"/dashboard/view/{provider_id}", status_code=303)

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# 2️⃣ Legacy Static Upload Endpoint (Postman Testing)
# ============================================================
@router.post("/ingest", summary="Legacy ingest (manual API mode)")
async def ingest_for_provider(file: UploadFile = File(...), provider_id: str = None):
    """Manual ingestion for Postman or backend-only tests."""
    if not provider_id:
        return JSONResponse(status_code=400, content={"error": "Missing provider_id"})

    provider_dir = Path("app/data/faiss_store") / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        await asyncio.to_thread(
            ingest_pdf,
            tmp_path,
            provider_id=provider_id,
            doc_name=file.filename,
        )
        return {"status": f"✅ File {file.filename} ingested for provider {provider_id}"}
    finally:
        os.remove(tmp_path)


# ============================================================
# 3️⃣ Ask Endpoint (Streaming Response + Metadata Awareness)
# ============================================================
@router.post("/ask")
async def ask_provider_docs(req: dict):
    """
    Stream AI answers for a provider using Azure OpenAI and FAISS context.
    """
    question = req.get("query", "")
    provider_id = req.get("provider_id", "")
    top_k = req.get("top_k", 3)

    if not question or not provider_id:
        return JSONResponse(status_code=400, content={"error": "Missing query or provider_id."})

    # --------------------------------------------------------
    # Step 1: Initialize client + embed query
    # --------------------------------------------------------
    client = AzureOpenAI(
        api_key=settings.OPENAI_KEY,
        api_version=settings.OPENAI_API_VERSION,
        azure_endpoint=settings.OPENAI_ENDPOINT,
    )

    query_vec = client.embeddings.create(
        input=question,
        model=settings.OPENAI_EMBEDDING_DEPLOYMENT,
    ).data[0].embedding

    provider_dir = Path("app/data/faiss_store") / provider_id
    if not provider_dir.exists():
        return JSONResponse(status_code=404, content={"error": "❌ No FAISS data found for this provider."})

    # --------------------------------------------------------
    # Step 2: Retrieve FAISS context
    # --------------------------------------------------------
    results = await asyncio.to_thread(
        query_faiss_index,
        np.array([query_vec], dtype="float32"),
        str(provider_dir),
        top_k,
    )

    context_text = "\n".join([r["text"] for r in results]) if results else "No relevant FAISS matches found."

    # --------------------------------------------------------
    # Step 3: Add metadata for uploaded files
    # --------------------------------------------------------
    apps_file = Path("app/data/applications.json")
    meta_text = ""
    if apps_file.exists():
        apps = json.loads(apps_file.read_text())
        rec = next((r for r in apps if r["id"] == provider_id), None)
        if rec and rec.get("documents"):
            filenames = [d["filename"] for d in rec["documents"]]
            meta_text = "\n\nProvider has uploaded these documents:\n" + "\n".join(f"- {f}" for f in filenames)
        elif rec:
            meta_text = "\n\nProvider has not uploaded any additional documents yet."

    full_context = f"{context_text}\n{meta_text}"

    # --------------------------------------------------------
    # Step 4: Streaming generator (safe and resilient)
    # --------------------------------------------------------
    def generate():
        try:
            stream = client.chat.completions.create(
                model=settings.OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert assistant that answers strictly from the given context. "
                            "If the question is about uploaded or attached files, list the files from metadata."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{full_context}\n\nQuestion: {question}",
                    },
                ],
                stream=True,
                temperature=0.2,
            )

            # ✅ Robust loop with guards
            for chunk in stream:
                # Some chunks may not have choices yet
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue

                choice = chunk.choices[0]
                if hasattr(choice, "delta") and getattr(choice.delta, "content", None):
                    yield choice.delta.content

            # End marker
            yield "[END]"

        except Exception as e:
            print(f"❌ Error during streaming: {e}")
            yield f"\n\n❌ Error during streaming: {e}"

    # --------------------------------------------------------
    # Step 5: Return the stream
    # --------------------------------------------------------
    return StreamingResponse(generate(), media_type="text/plain")


# ============================================================
# 4️⃣ Utility – List All Providers
# ============================================================
@router.get("/providers")
async def list_providers():
    """
    Lists all providers in FAISS with their document counts.
    """
    base_dir = Path("app/data/faiss_store")
    if not base_dir.exists():
        return []

    providers = []
    for pid in os.listdir(base_dir):
        pdir = base_dir / pid
        if not pdir.is_dir():
            continue
        docs = [f for f in os.listdir(pdir) if f.endswith(".index")]
        providers.append({"provider_id": pid, "documents": len(docs)})
    return providers
