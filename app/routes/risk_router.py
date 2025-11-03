# app/routes/risk_router.py

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime
from pathlib import Path
import json
import asyncio

from app.risk.orchestrator import evaluate_provider
from app.services.application_store import load_applications, save_all

router = APIRouter(tags=["Risk Intelligence"])

RISK_DIR = Path("app/data/risk")
RISK_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 1️⃣ CALCULATE / UPDATE PROVIDER RISK (MAIN ORCHESTRATOR ENTRY)
# ============================================================
@router.get("/calc/{provider_id}")
async def calculate_provider_risk(provider_id: str):
    """
    Triggers full Provider Risk Intelligence pipeline:
      • Runs all 7 watchlists concurrently
      • Fetches FAISS context & watchlist embeddings
      • Calls fine-tuned risk model (mock)
      • Persists risk summary & history
      • Returns final + pre-risk snapshot for drift visualization
      • Embeds latest risk summary for contextual RAG chat
    """
    try:
        print(f"⚙️ Starting risk evaluation for provider: {provider_id}")
        result = await evaluate_provider(provider_id)

        if not result:
            return JSONResponse(
                status_code=500,
                content={"error": f"Risk evaluation failed or empty result for {provider_id}."}
            )

        # --- Extract model response ---
        model_resp = result.get("model_response", {})
        aggregated_score = model_resp.get("aggregated_score")
        categories = model_resp.get("category_scores", {})
        timestamp = model_resp.get("timestamp", datetime.utcnow().isoformat())

        # Flatten for chart use
        flat_categories = {
            cat: val["score"] if isinstance(val, dict) else val
            for cat, val in categories.items()
        }

        # --- Persist into applications.json ---
        apps = load_applications()
        rec = None
        for r in apps:
            if r.get("id") == provider_id or r.get("application_id") == provider_id:
                rec = r
                r.setdefault("risk", {})
                r["risk"]["aggregated_score"] = aggregated_score
                r["risk"]["category_scores"] = categories
                r["risk"]["updated_at"] = timestamp
                r["risk_score"] = aggregated_score
                r["risk_level"] = (
                    "High" if aggregated_score and aggregated_score > 70 else
                    "Moderate" if aggregated_score and aggregated_score > 40 else
                    "Low"
                )
                r["risk_status"] = "Completed"

                # ✅ Add event log
                r.setdefault("history", []).append({
                    "event": "Risk Evaluation Completed",
                    "timestamp": datetime.utcnow().isoformat(),
                    "score": aggregated_score,
                    "note": "Final risk score updated and embedded."
                })
                break

        if not rec:
            return JSONResponse(status_code=404, content={"error": f"Provider {provider_id} not found"})

        save_all(apps)
        print(f"✅ Risk evaluation complete for {provider_id} — Score: {aggregated_score}")

        # --- Save full orchestrator output ---
        (RISK_DIR / f"{provider_id}.json").write_text(json.dumps(result, indent=2))

        # --- 🧠 Embed risk summary for chat context ---
        try:
            from app.rag.ingest import embed_texts
            from app.rag.vector_store_faiss import save_faiss_index
            import faiss

            # Build contextual summary text
            text_summary = (
                f"Provider Risk Assessment and Intelligence Summary\n"
                f"Provider ID: {provider_id}\n"
                f"Provider Name: {rec.get('provider', {}).get('provider_name', 'Unknown')}\n"
                f"License Number: {rec.get('provider', {}).get('license_number', 'N/A')}\n"
                f"Date of Evaluation: {timestamp}\n\n"
                f"--- OVERALL RISK SCORE BREAKDOWN ---\n"
                f"Total Risk Score: {aggregated_score}%\n"
                f"Risk Level: {rec.get('risk_level')}\n"
                f"Interpretation: This reflects the provider’s aggregate exposure across operational, regulatory, cybersecurity, financial, and reputation domains.\n\n"
                f"--- CATEGORY LEVEL RISK DETAILS ---\n"
            )


            for cat, val in categories.items():
                if isinstance(val, dict):
                    score = val.get("score", 0)
                    note = val.get("note", "No reason provided.")
                else:
                    score = val
                    note = "No reasoning provided."
                text_summary += f"- {cat.title()}: {score}% — {note}\n"


            # ✅ Add historical snapshot for richer context
            if pre_snapshot := rec.get("pre_risk_snapshot"):
                pre_text = (
                    f"\n📜 Previous Risk Snapshot:\n"
                    f"Score: {pre_snapshot.get('score', 'N/A')}%\n"
                )
                text_summary += pre_text

            # ✅ Add semantic-rich context for RAG search
            text_summary += (
                "\n--- SUMMARY INSIGHTS ---\n"
                "This report provides a detailed risk score breakdown per category and the rationale behind each rating. "
                "It helps explain how the provider's operational, financial, regulatory, cybersecurity, and reputation domains "
                "contribute to the overall score.\n\n"
                "Example questions that can be answered using this context:\n"
                "- What is the provider's overall risk?\n"
                "- How much risk is attributed to cybersecurity?\n"
                "- Explain the reasoning behind the regulatory risk score.\n"
                "- Show me the risk score breakdown per category.\n"
            )


            # === Embed summary into FAISS ===
            vectors = embed_texts([text_summary])
            faiss.normalize_L2(vectors)

            provider_dir = Path('app/data/faiss_store') / provider_id
            provider_dir.mkdir(parents=True, exist_ok=True)

            # ✅ Clean up any stale FAISS index before re-embedding
            index_file = provider_dir / "index.faiss"
            if index_file.exists():
                index_file.unlink()

            save_faiss_index(
                vectors=vectors,
                chunks=[text_summary],
                doc_id=provider_id,
                provider_dir=str(provider_dir)
            )
            print(f"💾 Risk summary embedded for provider {provider_id}")
        except Exception as e:
            print(f"⚠️ Failed to embed risk summary for {provider_id}: {e}")

        # --- Include pre-risk snapshot for drift chart ---
        pre_snapshot = rec.get("pre_risk_snapshot", {})
        if not pre_snapshot:
            pre_snapshot = {"score": 0, "categories": {}, "timestamp": None}

        # --- Build response ---
        response = {
            "provider_id": provider_id,
            "risk_score": aggregated_score,
            "risk_level": rec.get("risk_level"),
            "categories": categories,
            "timestamp": timestamp,
            "pre_snapshot": pre_snapshot,  # ✅ Added for drift chart
        }

        # ✅ Optional dashboard refresh notifier (placeholder)
        print(f"📢 Dashboard notified: Risk updated for {provider_id}")

        return JSONResponse(content=response)

    except Exception as e:
        print(f"❌ Risk calculation failed for {provider_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})



# ============================================================
# 2️⃣ GET EXISTING PROVIDER RISK STATUS (FOR DASHBOARD OR API)
# ============================================================
@router.get("/status/{provider_id}")
async def get_risk_status(provider_id: str):
    """
    Returns the most recently computed risk profile for a provider.
    Used by Provider Dashboard and API clients.
    """
    apps = load_applications()
    rec = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None,
    )
    if not rec:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    risk = rec.get("risk", {})
    status = rec.get("risk_status", "Pending")
    score = rec.get("risk_score") or risk.get("aggregated_score")
    level = rec.get("risk_level") or "Unknown"
    categories = risk.get("category_scores", {}) or {}

    if score is not None:
        status = "Completed"

    return JSONResponse(
        content={
            "status": status,
            "score": score,
            "level": level,
            "categories": categories,
            "last_updated": risk.get("updated_at", datetime.utcnow().isoformat()),
        }
    )


# ============================================================
# 3️⃣ MANUAL REFRESH (RE-EVALUATE PROVIDER)
# ============================================================
@router.post("/refresh/{provider_id}")
async def refresh_risk(provider_id: str):
    """
    Allows manual re-triggering of risk calculation (async).
    """
    try:
        asyncio.create_task(evaluate_provider(provider_id))
        return JSONResponse(content={"status": "Re-evaluation initiated", "provider_id": provider_id})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
