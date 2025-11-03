# app/risk/orchestrator.py
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from app.risk.watchlist_simulator import CATEGORIES, simulate_watchlist_call
from app.services.application_store import load_applications, save_all  # reuse your persistence
from app.rag.vector_store_faiss import query_faiss_index  # optional use
# optional import for summarization if available
try:
    from app.rag.ingest import summarize_pdf_text  # optional contextual summarization
except ImportError:
    summarize_pdf_text = None  # fallback if not implemented yet

RISK_DIR = Path("app/data/risk")
RISK_DIR.mkdir(parents=True, exist_ok=True)
RISK_HISTORY_DIR = Path("app/data/risk_history")
RISK_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# --- mocked finetuned risk intelligence call (for POC) ---
async def call_risk_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mocked risk intelligence model. Replace with real API call to your finetuned model.
    Returns per-category scores (0-100), notes, and aggregated score.
    """
    scores = {}
    for cat, w in payload.get("watchlists", {}).items():
        entries = w.get("entries", [])
        note = w.get("raw_simulated", {}).get("note", "No details available.")
        if not entries:
            score_val = 10  # baseline low risk
        else:
            avg_sev = sum(e.get("severity", 0.3) for e in entries) / max(1, len(entries))
            score_val = int(min(95, max(10, avg_sev * 100)))

        # 🧠 include reasoning note
        scores[cat] = {
            "score": score_val,
            "note": note
        }

    aggregated = int(sum(v["score"] for v in scores.values()) / max(1, len(scores)))
    return {
        "request_id": payload.get("request_id", "sim-req"),
        "provider_id": payload["provider"].get("provider_id"),
        "category_scores": scores,
        "aggregated_score": aggregated,
        "notes": "Simulated risk model response with reasoning notes.",
        "confidence": 0.9,
        "model_version": "risk-sim-v0.2",
        "timestamp": datetime.utcnow().isoformat(),
    }


async def evaluate_provider(provider_id: str, fire_watchlists=True, include_faiss_context=True) -> Dict[str, Any]:
    """Main orchestrator function to evaluate risk for a provider_id."""
    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id), None)
    if not rec:
        raise ValueError(f"Provider {provider_id} not found")

    provider_name = (rec.get("provider") or {}).get("provider_name") or rec.get("provider_name") or "Unknown"
    license_number = (rec.get("provider") or {}).get("license_number") or rec.get("license_number") or "UNKNOWN"

    # 1) Run watchlist calls concurrently
    watchlist_results = {}
    if fire_watchlists:
        tasks = [simulate_watchlist_call(provider_name, license_number, cat) for cat in CATEGORIES]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for r in results:
            watchlist_results[r["category"]] = r
    else:
        for cat in CATEGORIES:
            watchlist_results[cat] = {"category": cat, "hits": 0, "entries": []}

    # 2) Optional: fetch FAISS snippets (best-effort)
    faiss_snippets = []
    try:
        if include_faiss_context:
            # try to fetch a tiny context to feed model
            # NOTE: your query vector creation logic could be more advanced; here keep simple
            # If query_faiss_index not available for import (for POC) skip
            try:
                import numpy as np
                vect = np.random.rand(1, 1536).astype("float32")  # dummy query vector
                raw = await asyncio.to_thread(query_faiss_index, vect, str(Path("app/data/faiss_store") / provider_id), 3)
                if raw:
                    faiss_snippets = [{"text": r.get("text"), "score": r.get("score", 0)} for r in raw]
            except Exception:
                faiss_snippets = []
    except Exception:
        faiss_snippets = []

    # === Embed watchlist textual summaries (so risk model receives semantic vectors) ===
    watchlist_embeddings = []
    try:
        # import embedding helper (wrap in try so POC still runs if missing)
        from app.rag.ingest import embed_texts
        import faiss
        import numpy as np

        # collect texts
        watchlist_texts = []
        wl_meta = []  # keep mapping for later
        for cat, data in watchlist_results.items():
            for e in data.get("entries", []):
                txt = f"[{cat}] {e.get('title','')}: {e.get('detail','')}"
                watchlist_texts.append(txt)
                wl_meta.append({"category": cat, "entry_id": e.get("id")})

        if watchlist_texts:
            vectors = embed_texts(watchlist_texts)  # expected: numpy array or list of vectors
            # normalize & convert to plain lists for JSON persistence (safe)
            try:
                faiss.normalize_L2(vectors)
            except Exception:
                pass
            # ensure we can JSON-serialize: convert numpy arrays to lists
            for txt, vec, meta in zip(watchlist_texts, vectors, wl_meta):
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                watchlist_embeddings.append({"text": txt, "embedding": vec_list, **meta})
    except Exception as e:
        # don't fail the whole evaluation if embedding is broken — log and continue
        print(f"⚠️ watchlist embedding skipped: {e}")
        watchlist_embeddings = []

    # 3) Assemble payload
    payload = {
        "request_id": f"risk-{provider_id}-{int(datetime.utcnow().timestamp())}",
        "provider": {
            "provider_id": provider_id,
            "provider_name": provider_name,
            "license_number": license_number
        },
        "watchlists": watchlist_results,
        # 🧠 include embeddings from FAISS, contextual docs, and watchlist text embeddings
        "embedded_context": {
            "faiss_snippets": faiss_snippets,
            "contextual_documents": rec.get("documents", []),
            "watchlist_embeddings": watchlist_embeddings
        },
        "config": {"model_version": "sim-1"}
    }


    # 4) Call risk model (mock)
    model_resp = await call_risk_model(payload)

    # 5) Persist results (single file and history)
    out = {
        "payload": payload,
        "model_response": model_resp,
        "timestamp": datetime.utcnow().isoformat()
    }
    (RISK_DIR / f"{provider_id}.json").write_text(json.dumps(out, indent=2))

    # append to history
    hist_file = RISK_HISTORY_DIR / f"{provider_id}.json"
    history = json.loads(hist_file.read_text()) if hist_file.exists() else []
    history.append({"timestamp": datetime.utcnow().isoformat(), "result": out})
    hist_file.write_text(json.dumps(history, indent=2))

    # 6) Optionally update the application record with latest risk summary
    # keep this minimal: add risk_summary in record and save_all
# 6️⃣ Update the application record with the latest risk summary
    rec.setdefault("risk", {})
    rec["risk"]["aggregated_score"] = model_resp["aggregated_score"]
    rec["risk"]["category_scores"] = model_resp["category_scores"]
    rec["risk"]["updated_at"] = model_resp["timestamp"]

    # Store flattened fields for quick dashboard access
    rec["risk_score"] = model_resp["aggregated_score"]
    rec["risk_level"] = (
        "High" if rec["risk_score"] > 70 else
        "Moderate" if rec["risk_score"] > 40 else
        "Low"
    )
    rec["risk_status"] = "Completed"

    # ✅ Persist back into applications.json (using same in-memory apps list)
    save_all(apps)
    print(f"✅ Risk evaluation complete for {provider_id} — Score: {rec['risk_score']}")

    return out
