# app/risk/orchestrator.py
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from app.risk.scoring import compute_scores_from_watchlists
from app.risk.watchlist_simulator import simulate_all_watchlists
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
    # 0️⃣ Generate simulated watchlist JSON files
    # ============================================================
# ============================================================
# 0️⃣ Generate simulated watchlist JSON files (FULL SIMULATOR)
# ============================================================
    from app.risk.watchlist_simulator import simulate_all_watchlists

    print(f"🧪 Generating simulated watchlists for provider {provider_id} (FULL SIMULATOR)...")

    # This MUST run BEFORE we try loading files
    await simulate_all_watchlists(provider_id)

    # Confirm files exist
    provider_dir = Path("app/mock_data/watchlists") / provider_id
    print(f"📁 Watchlist directory: {provider_dir}  Exists? {provider_dir.exists()}")


    # ============================================================
    # 1️⃣ Build REAL model payload from actual watchlist JSONs
    # ============================================================
    watchlist_categories = []
    provider_dir = Path("app/mock_data/watchlists") / provider_id


    for cat in [
        "cybersecurity", "data_privacy", "financial",
        "operational", "regulatory", "reputation", "supplychain"
    ]:
        file_path = provider_dir / f"{cat}.json"
        if file_path.exists():
            data = json.loads(file_path.read_text())

            # 🔧 normalize to match what model prompt builder expects
            note = data.get("note") or data.get("raw_simulated", {}).get("note", "")
            data["note"] = note

            watchlist_categories.append(data)
        else:
            print(f"⚠️ Missing watchlist file for {cat}")


    # Build payload for the model
    payload = {
        "provider_name": name,
        "license_number": license_num,
        "web_research": "No web research available.",
        "doc_summary": "No document summary available.",
        "watchlist_categories": watchlist_categories,
    }


    # ============================================================
    # 2️⃣ Call fine-tuned model — expect ONLY explanations
    # ============================================================
    try:
        # previously you might have: raw_result = call_risk_model(payload, model)
        # 1️⃣ Build real YAML-style prompt for the fine-tuned model
        text_prompt = convert_payload_to_text_prompt(payload)

        # 2️⃣ Debug logs BEFORE calling the model
        print("=== Sending text prompt to risk model (length:", len(text_prompt), ") ===")
        print(text_prompt[:2000])
        print("\n--- END OF TRUNCATED TEXT PROMPT PREVIEW ---\n")

        # 3️⃣ Call Azure OpenAI fine-tuned model
        raw_result = await call_risk_model(
            text_prompt,
            model_name="gpt-4o-mini-2024-07-18-risk-eval-v2"
        )




        # risk_model_client returns string or dict
        if isinstance(raw_result, str):
            try:
                model_output = json.loads(raw_result)
            except:
                print("⚠️ Model returned non-JSON. Using fallback explanations only.")
                model_output = {}
        elif isinstance(raw_result, dict):
            model_output = raw_result
        else:
            model_output = {}

        print("\n==================== MODEL OUTPUT (PARSED) ====================")
        print(json.dumps(model_output, indent=2))
        print("==============================================================\n")

    except Exception as e:
        print(f"❌ Model call failed: {e}")
        model_output = {}

    # ============================================================
    # 3️⃣ Compute deterministic backend scores from watchlist severity
    # ============================================================
    det_scores = compute_scores_from_watchlists(watchlist_categories)

    # Model returns: {"category_explanations": {...}}  OR  {"category_scores": {...}}
    model_expl = model_output.get("category_explanations", {})
    model_cat_scores = model_output.get("category_scores", {})

    # ============================================================
    # 4️⃣ Merge deterministic scores + model explanations
    # ============================================================
    final_categories = {}

    for cat, score in det_scores.items():

        # Find note priority:
        # 1) model_expl[cat]
        # 2) model_cat_scores[cat]['note']
        # 3) watchlist[data]['note']
        wl_note = next((c["note"] for c in watchlist_categories if c["category"] == cat), "")

        if model_expl and cat in model_expl:
            note = model_expl[cat]
        elif model_cat_scores and cat in model_cat_scores:
            mc = model_cat_scores[cat]
            note = mc["note"] if isinstance(mc, dict) else str(mc)
        else:
            note = wl_note or "No explanation available."

        final_categories[cat] = {"score": score, "note": note}

    # ============================================================
    # 5️⃣ Compute final aggregated score
    # ============================================================
    aggregated_score = round(sum(v["score"] for v in final_categories.values()) / len(final_categories), 1)

    if aggregated_score > 70:
        risk_level = "High"
    elif aggregated_score > 40:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    confidence = model_output.get("confidence", 0.0)

    timestamp = datetime.utcnow().isoformat()

    model_response = {
        "provider_name": name,
        "license_number": license_num,
        "aggregated_score": aggregated_score,
        "risk_level": risk_level,
        "category_scores": final_categories,
        "confidence": confidence,
        "timestamp": timestamp
    }

    # ============================================================
    # 4️⃣ Persist results
    # ============================================================
    record["risk_status"] = "Completed"
    record["risk_score"] = aggregated_score
    record["risk_level"] = risk_level
    # Do NOT overwrite the entire record["risk"]
    record.setdefault("risk", {})
    record["risk"]["aggregated_score"] = aggregated_score
    record["risk"]["risk_level"] = risk_level
    record["risk"]["category_scores"] = final_categories

    record["risk"]["confidence"] = confidence
    record["risk"]["timestamp"] = timestamp

    # DO NOT WRITE original_explanations HERE.
    # They must only be added by risk_router.py after merging.

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


def convert_payload_to_text_prompt(payload: dict) -> str:
    """
    Convert the canonical payload into the YAML-like text prompt
    your finetuned model expects.
    """
    lines = []
    lines.append("Category-wise risk factors:")
    lines.append(f"provider_name: {payload.get('provider_name', '')}")
    lines.append(f"license_number: {payload.get('license_number', '')}")
    lines.append("watchlists:")
    for cat in payload.get("watchlist_categories", []):
        # hits
        hits = cat.get("hits", 0)
        lines.append(f"- {cat.get('category')}: {hits} hits")
        lines.append("  entries:")
        entries = cat.get("entries", []) or []
        if not entries:
            lines.append("    []")
        else:
            for e in entries:
                # use common keys if present (case-insensitive)
                idv = e.get("id") or e.get("ID") or e.get("Id") or ""
                title = e.get("title") or e.get("Title") or ""
                detail = e.get("detail") or e.get("Detail") or e.get("description") or ""
                severity = e.get("severity") or e.get("Severity") or ""
                source = e.get("source") or e.get("Source") or ""
                timestamp = e.get("timestamp") or e.get("Timestamp") or ""
                if idv:
                    lines.append(f"    - ID: {idv}")
                if title:
                    lines.append(f"      Title: {title}")
                if detail:
                    lines.append(f"      Detail: {detail}")
                if severity != "":
                    lines.append(f"      Severity: {severity}")
                if source:
                    lines.append(f"      Source: {source}")
                if timestamp:
                    lines.append(f"      Timestamp: {timestamp}")
        note = cat.get("note", "")
        # escape quotes
        note_escaped = note.replace('"', "'")
        lines.append(f"  note: \"{note_escaped}\"")
        lines.append("")  # blank line
    lines.append(f"web_research: '{payload.get('web_research', '')}'")
    lines.append(f"doc_summary: '{payload.get('doc_summary', '')}'")
    lines.append("Produce JSON as specified.")
    return "\n".join(lines)
