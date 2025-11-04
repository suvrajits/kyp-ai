# app/risk/orchestrator.py
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from app.risk.watchlist_simulator import CATEGORIES, simulate_watchlist_call, simulate_all_watchlists

from app.services.application_store import load_applications, save_all  # reuse your persistence
from app.rag.vector_store_faiss import query_faiss_index  # optional use
# optional import for summarization if available
try:
    from app.rag.ingest import summarize_pdf_text  # optional contextual summarization
except ImportError:
    summarize_pdf_text = None  # fallback if not implemented yet

CATEGORY_WEIGHTS = {
    "cybersecurity": 1.2,
    "data_privacy": 1.1,
    "operational": 1.0,
    "financial": 1.0,
    "regulatory": 1.1,
    "reputation": 0.9,
    "supplychain": 0.8,
}


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


async def evaluate_provider(provider_id: str) -> Dict[str, Any]:
    """
    Main orchestrator for provider-level risk evaluation.
    Uses realistic watchlist simulation + weighted aggregation.
    """

    from app.services.application_store import load_applications, save_all

    apps = load_applications()
    record = next((r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id), None)
    if not record:
        print(f"❌ No record found for provider {provider_id}")
        return None

    provider = record.get("provider", {})
    name = provider.get("provider_name", "Unknown Provider")
    license_num = provider.get("license_number", "N/A")

    print(f"🧠 [Pipeline] Evaluating provider risk for {provider_id}...")

    # --- 1️⃣ Simulate multi-watchlist calls (1–3 categories active)
    watchlist_results = await simulate_all_watchlists(name, license_num)

    # --- 2️⃣ Compute category-level severity scores
    category_scores = {}
    total_weighted = 0.0
    total_weight = 0.0

    for result in watchlist_results:
        cat = result["category"]
        entries = result.get("entries", [])
        hits = len(entries)

        # ✅ Safe log — no undefined variable usage
        if hits > 0:
            print(f"📂 [Watchlist] {cat}: {hits} hit(s) detected.")
        else:
            print(f"📂 [Watchlist] {cat}: No alerts found (clean).")


        # If no entries, give a low baseline score (almost safe)
        if hits == 0:
            avg_score = 5.0  # baseline
            note = result["raw_simulated"]["note"]
        else:
            avg_severity = sum(e["severity"] for e in entries) / len(entries)
            avg_score = round(avg_severity * 100, 1)
            note = result["raw_simulated"]["note"]

        # Weighted contribution
        weight = CATEGORY_WEIGHTS.get(cat, 1.0)
        total_weighted += avg_score * weight
        total_weight += weight

        # Optional descriptive reasoning per category
        if hits == 0:
            category_reason = f"{note.strip()}"
        else:
            category_reason = f"{note.strip()} {hits} alert(s) identified with average severity {avg_score}%."


        category_scores[cat] = {
            "score": avg_score,
            "note": category_reason,
            "hits": hits,
            "last_reported": result.get("last_reported"),
        }

    # --- 3️⃣ Aggregate overall risk score
    aggregated_score = round(total_weighted / max(total_weight, 1.0), 1)

    # --- 4️⃣ Derive qualitative risk level
    if aggregated_score > 70:
        risk_level = "High"
    elif aggregated_score > 40:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    timestamp = datetime.utcnow().isoformat()

    model_response = {
        "provider_name": name,
        "license_number": license_num,
        "aggregated_score": aggregated_score,
        "category_scores": category_scores,
        "risk_level": risk_level,
        "timestamp": timestamp,
        "summary": (
            f"Provider '{name}' evaluated across {len(CATEGORIES)} domains. "
            f"{len([c for c in category_scores.values() if c['hits']>0])} category(ies) showed alerts. "
            f"Overall risk assessed as {risk_level} ({aggregated_score}%)."
        ),
    }

    # --- 5️⃣ Update persistent record
    record["risk_status"] = "Completed"
    record["risk_score"] = aggregated_score
    record["risk_level"] = risk_level
    record["risk"] = model_response
    record.setdefault("history", []).append({
        "event": "Risk Evaluation Completed",
        "timestamp": timestamp,
        "score": aggregated_score,
        "note": f"Auto-evaluated risk level: {risk_level}",
    })

    save_all(apps)
    # --- 🧾 Persist standalone risk file for dashboard ---
    risk_output = {"model_response": model_response}
    risk_file = RISK_DIR / f"{provider_id}.json"
    risk_file.write_text(json.dumps(risk_output, indent=2))
    print(f"💾 Risk file saved: {risk_file}")

    print(f"✅ [Pipeline] Risk model evaluation done for {provider_id} → {risk_level} ({aggregated_score}%)")
    return {"model_response": model_response}