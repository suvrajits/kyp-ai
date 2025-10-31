# app/routes/search.py

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from app.services.application_store import load_applications
from app.services.embedding_utils import embed_single_text, embed_text_batch, get_azure_openai_client
import faiss, numpy as np, os, json
from datetime import datetime

router = APIRouter()

FAISS_ROOT = "app/data/faiss_store"
SIMILARITY_THRESHOLD = 0.25  # adjusted for deterministic embeddings


@router.get("/semantic")
async def search_semantic(q: str = Query(..., description="Smart provider search query")):
    """
    Global provider search (GPT intent + FAISS semantic similarity).
    Matches structure used in provider_dashboard.py.
    """
    print(f"\n🔎 Incoming query: {q}")
    results = []
    interpreted_intent = {"intent": "local_search", "filters": {}}

    # ------------------------------------------------------------
    # Step 1: Load provider applications
    # ------------------------------------------------------------
    apps = load_applications()
    print(f"📂 Loaded {len(apps)} application(s).")

    # ------------------------------------------------------------
    # Step 2: Embed query
    # ------------------------------------------------------------
    try:
        query_vec = embed_single_text(q).reshape(1, -1).astype("float32")
        faiss.normalize_L2(query_vec)
    except Exception as e:
        return JSONResponse(content={"error": f"Embedding failed: {e}"}, status_code=500)

    # ------------------------------------------------------------
    # Step 3: Iterate all provider FAISS indices
    # ------------------------------------------------------------
    if not os.path.exists(FAISS_ROOT):
        return JSONResponse(content={"error": "FAISS store not found."}, status_code=404)

    provider_dirs = [
        os.path.join(FAISS_ROOT, d)
        for d in os.listdir(FAISS_ROOT)
        if os.path.isdir(os.path.join(FAISS_ROOT, d))
    ]

    for provider_dir in provider_dirs:
        app_id = os.path.basename(provider_dir)
        try:
            index_files = [f for f in os.listdir(provider_dir) if f.endswith(".index")]
            if not index_files:
                continue

            for idx_file in index_files:
                index_path = os.path.join(provider_dir, idx_file)
                npy_path = index_path.replace(".index", "_chunks.npy")

                if not os.path.exists(npy_path):
                    continue

                chunks = np.load(npy_path, allow_pickle=True)
                if chunks.dtype.type is np.str_ or isinstance(chunks[0], str):
                    chunks = embed_text_batch(list(chunks))
                chunks = np.array(chunks, dtype="float32", ndmin=2)
                faiss.normalize_L2(chunks)

                # Load FAISS index
                index = faiss.read_index(index_path)
                if index.ntotal == 0:
                    continue

                # Compute similarity
                D, I = index.search(query_vec, 1)
                score = float(D[0][0]) if len(D[0]) else 0.0

                # Apply similarity threshold
                if score < SIMILARITY_THRESHOLD:
                    continue

                # Load metadata
                record = next(
                    (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
                    None,
                )
                if not record or not record.get("provider"):
                    continue

                provider = record["provider"]
                provider_name = provider.get("provider_name", "Unknown")

                # Literal match boost
                if q.lower() in " ".join(map(str, provider.values())).lower():
                    score = max(score, 0.95)

                print(f"   → {provider_name} | score={round(score,4)}")

                provider["similarity"] = round(score, 4)
                provider["app_id"] = app_id
                provider["view_url"] = f"/view/{app_id}"
                results.append(provider)

        except Exception as e:
            print(f"⚠️ Error scanning {app_id}: {e}")
            continue

    # ------------------------------------------------------------
    # Step 4: Sort & return
    # ------------------------------------------------------------
    results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
    match_count = len(results)

    if not results:
        print("⚠️ No providers matched this query.")
    else:
        print(f"✅ Found {match_count} relevant provider(s).")

    return {
        "query": q,
        "timestamp": datetime.utcnow().isoformat(),
        "interpreted_intent": interpreted_intent,
        "results": results,
        "match_count": match_count,
    }
