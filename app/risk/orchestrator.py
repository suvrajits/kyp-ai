# app/risk/orchestrator.py
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from app.services.application_store import load_applications, save_all
from app.services.risk_model_client import call_risk_model  # ✅ new module using Azure Key Vault secrets

# optional imports (not required for risk model call)
try:
    from app.rag.ingest import summarize_pdf_text
except ImportError:
    summarize_pdf_text = None

# ============================================================
# 📁 Directories
# ============================================================
RISK_DIR = Path("app/data/risk")
RISK_DIR.mkdir(parents=True, exist_ok=True)
RISK_HISTORY_DIR = Path("app/data/risk_history")
RISK_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 🧠 Evaluate Provider Risk (via fine-tuned model)
# ============================================================
async def evaluate_provider(provider_id: str) -> Dict[str, Any]:
    """
    Main orchestrator for provider-level risk evaluation.
    Uses fine-tuned Azure OpenAI model via secure Key Vault credentials.
    """

    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None,
    )
    if not record:
        print(f"❌ No record found for provider {provider_id}")
        return None

    provider = record.get("provider", {})
    name = provider.get("provider_name", "Unknown Provider")
    license_num = provider.get("license_number", "N/A")

    print(f"🧠 [Pipeline] Evaluating provider risk for {provider_id} using fine-tuned model...")

    # ============================================================
    # 1️⃣ Build model payload
    # ============================================================
    payload = {
        "provider_name": name,
        "license_number": license_num,
        "watchlists": record.get("watchlists", {}),
        "web_research": record.get("web_research", "No web research data."),
        "doc_summary": record.get("doc_summary", "No document summary available."),
    }

    # ============================================================
    # 2️⃣ Query fine-tuned model
    # ============================================================
    try:
        model_output = await call_risk_model(payload)
    except Exception as e:
        print(f"❌ [RiskModel] Model call failed: {e}")
        # fallback stub so the pipeline doesn’t break
        model_output = {
            "aggregated_score": 0,
            "risk_level": "Error",
            "category_scores": {},
            "confidence": 0.0,
            "notes": str(e),
        }

    # ============================================================
    # 3️⃣ Parse model response
    # ============================================================
    aggregated_score = model_output.get("aggregated_score", 0)
    risk_level = model_output.get("risk_level", "Unknown")
    category_scores = model_output.get("category_scores", {})
    confidence = model_output.get("confidence", 0.0)

    timestamp = datetime.utcnow().isoformat()

    model_response = {
        "provider_name": name,
        "license_number": license_num,
        "aggregated_score": aggregated_score,
        "risk_level": risk_level,
        "category_scores": category_scores,
        "confidence": confidence,
        "timestamp": timestamp,
        "summary": f"Fine-tuned model evaluation complete. Risk level: {risk_level} ({aggregated_score}%), confidence: {confidence}.",
    }

    # ============================================================
    # 4️⃣ Persist results
    # ============================================================
    record["risk_status"] = "Completed"
    record["risk_score"] = aggregated_score
    record["risk_level"] = risk_level
    record["risk"] = model_response
    record.setdefault("history", []).append({
        "event": "Risk Evaluation Completed (Fine-Tuned Model)",
        "timestamp": timestamp,
        "score": aggregated_score,
        "note": f"Model returned {risk_level} with confidence {confidence}",
    })

    save_all(apps)

    # ============================================================
    # 5️⃣ Save risk snapshot to disk for dashboard
    # ============================================================
    risk_file = RISK_DIR / f"{provider_id}.json"
    risk_file.write_text(json.dumps(model_response, indent=2))
    print(f"💾 Risk file saved: {risk_file}")

    print(f"✅ [Pipeline] Risk evaluation completed for {provider_id} → {risk_level} ({aggregated_score}%)")
    return {"model_response": model_response}

if __name__ == "__main__":
    import asyncio
    print("🔍 Running standalone test for evaluate_provider()...")
    asyncio.run(evaluate_provider("APP-TEST-001"))
