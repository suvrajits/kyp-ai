# app/routes/risk_router.py

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
from pathlib import Path
import json
import asyncio

from app.risk.orchestrator import evaluate_provider
from app.services.application_store import load_applications, save_all
from app.rag.ingest import ingest_text_block
router = APIRouter(tags=["Risk Intelligence"])

RISK_DIR = Path("app/data/risk")
RISK_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 1️⃣ CALCULATE / UPDATE PROVIDER RISK (MAIN ORCHESTRATOR ENTRY)
# ============================================================
@router.post("/calc/{provider_id}")
async def calculate_provider_risk(provider_id: str, internal: bool = False):
    """
    Triggers full Provider Risk Intelligence pipeline.
    Can be called externally (HTTP) or internally (programmatically) after acceptance.

      • Runs all 7 watchlists concurrently
      • Fetches FAISS context & watchlist embeddings
      • Calls fine-tuned (or mock) risk model
      • Persists risk summary & history
      • Returns final + pre-risk snapshot for drift visualization
      • Embeds latest risk summary into FAISS for contextual RAG chat
    """
    try:
        if internal:
            print(f"🧠 [Internal] Triggering risk calculation for {provider_id}")
        else:
            print(f"⚙️ Starting risk evaluation for provider: {provider_id}")

        # --- Run risk evaluation orchestrator ---
        result = await evaluate_provider(provider_id)
        if not result:
            msg = f"Risk evaluation failed or empty result for {provider_id}."
            print(f"❌ {msg}")
            if internal:
                return {"status": "error", "message": msg}
            return JSONResponse(status_code=500, content={"error": msg})

        # --- Extract model response ---
        model_resp = result.get("model_response", {})
        # aggregated_score = model_resp.get("aggregated_score")
        




        categories = model_resp.get("category_scores", {})
        aggregated_score = model_resp.get("aggregated_score", 0)
        print("\n\n==================== RISK ROUTER RECEIVED ====================")
        print("Aggregated (model-provided, before override):", model_resp.get("aggregated_score"))
        print("Categories:", json.dumps(categories, indent=2))
        print("Original_explanations:", model_resp.get("original_explanations"))
        print("==============================================================\n")

        timestamp = model_resp.get("timestamp", datetime.utcnow().isoformat())
        # ============================================================
        # 🧠 PRESERVE ORIGINAL CATEGORY EXPLANATIONS
        # ============================================================

        # Load existing record to check for previous explanations
        apps_existing = load_applications()
        record_existing = next(
            (r for r in apps_existing if r.get("id") == provider_id or r.get("application_id") == provider_id),
            None
        )

        previous_notes = None

        if record_existing:
            previous_notes = (
                record_existing.get("risk", {}).get("original_explanations")
                or {cat: data.get("note") for cat, data in 
                record_existing.get("risk", {}).get("category_scores", {}).items()}
            )

        # If we already have original explanations → reattach them
        # ============================================================
        # 🧠 FULL 7-CATEGORY MERGE — MODEL MAY RETURN ONLY SOME
        # ============================================================

        merged = {}

        # 1️⃣ Load previous categories (full set of 7, if they exist)
        previous_categories = {}
        if record_existing:
            previous_categories = record_existing.get("risk", {}).get("category_scores", {})

        # 2️⃣ Merge across full set
        all_category_keys = set(previous_categories.keys()) | set(categories.keys())

        for cat in all_category_keys:
            # Determine score
            if cat in categories:  # new score from model
                model_val = categories[cat]
                new_score = model_val.get("score") if isinstance(model_val, dict) else model_val
            else:
                # Model did not return this category → reuse old score OR set default
                old_val = previous_categories.get(cat, {})
                new_score = old_val.get("score", 0)

            # Determine explanation
            if previous_notes and cat in previous_notes:
                note = previous_notes[cat]
            elif cat in previous_categories:
                note = previous_categories[cat].get("note", "No explanation provided.")
            else:
                note = "No explanation available."

            merged[cat] = {
                "score": new_score,
                "note": note
            }

        # 3️⃣ Replace model categories with merged full set
        categories = merged
        model_resp["category_scores"] = merged



        # ============================================================
        # ✅ FIX #3 — Ensure authoritative original_explanations
        # ============================================================
        if record_existing and previous_notes:
            # If previous notes exist, ALWAYS use them as the source of truth
            model_resp["original_explanations"] = previous_notes

        # --- ✅ Normalize category_scores to always include {score, note}
        if isinstance(categories, dict):
            normalized = {}
            for cat, val in categories.items():
                if isinstance(val, (int, float)):
                    # Wrap numeric-only entries with default reasoning
                    normalized[cat] = {
                        "score": val,
                        "note": "No reasoning available (model returned numeric-only score)."
                    }
                elif isinstance(val, dict):
                    # Determine the note: priority → val.note → val.reason → previous_notes → fallback
                    note_val = (
                        val.get("note")
                        or val.get("reason")
                        or (previous_notes.get(cat) if previous_notes else None)
                        or "No reasoning provided."
                    )

                    normalized[cat] = {
                        "score": val.get("score", 0),
                        "note": note_val
                    }

                else:
                    normalized[cat] = {
                        "score": 0,
                        "note": "Invalid category value format."
                    }
            categories = normalized
            model_resp["category_scores"] = normalized
            
            WEIGHTS = {
                "reputation": 0.25,
                "regulatory": 0.20,
                "operational": 0.15,
                "financial": 0.15,
                "cybersecurity": 0.10,
                "data_privacy": 0.10,
                "supplychain": 0.05,
            }

            weighted_sum = 0.0
            total_weight = 0.0

            for cat, data in categories.items():
                score = data.get("score", 0)
                weight = WEIGHTS.get(cat, 0)
                weighted_sum += score * weight
                total_weight += weight

            if total_weight > 0:
                aggregated_score = round(weighted_sum / total_weight, 1)
            else:
                aggregated_score = 0

            model_resp["aggregated_score"] = aggregated_score

            print("\n\n==================== RISK ROUTER POST-MERGE ====================")
            print(json.dumps(model_resp["category_scores"], indent=2))
            print("================================================================\n")



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
                # NEW → persist original explanations so future runs can reattach them
                if "original_explanations" in model_resp:
                    for cat, note in model_resp["original_explanations"].items():
                        if cat in categories:
                            categories[cat]["note"] = note

                    # Persist permanently
                    r["risk"]["original_explanations"] = model_resp["original_explanations"]



                r["risk_score"] = aggregated_score
                r["risk_level"] = (
                    "High" if aggregated_score and aggregated_score > 60 else
                    "Moderate" if aggregated_score and aggregated_score > 30 else
                    "Low"
                )
                r["risk_status"] = "Completed"
                r.setdefault("history", []).append({
                    "event": "Risk Evaluation Completed",
                    "timestamp": datetime.utcnow().isoformat(),
                    "score": aggregated_score,
                    "note": "Final risk score updated and embedded."
                })
                break

        if not rec:
            msg = f"Provider {provider_id} not found in applications.json"
            print(f"❌ {msg}")
            if internal:
                return {"status": "error", "message": msg}
            return JSONResponse(status_code=404, content={"error": msg})

        save_all(apps)
        print(f"✅ Risk evaluation complete for {provider_id} — Score: {aggregated_score}")

        # --- Save orchestrator output snapshot ---
        (RISK_DIR / f"{provider_id}.json").write_text(json.dumps(result, indent=2))

        # --- 🧠 Build contextual summary text for FAISS embedding ---
        from app.rag.ingest import embed_texts
        from app.rag.vector_store_faiss import save_faiss_index
        import faiss

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
                score, note = val, "No reasoning provided."
            text_summary += f"- {cat.title()}: {score}% — {note}\n"

        # ✅ Historical context for drift
        if pre_snapshot := rec.get("pre_risk_snapshot"):
            text_summary += (
                f"\n📜 Previous Risk Snapshot:\n"
                f"Score: {pre_snapshot.get('score', 'N/A')}%\n"
            )

        text_summary += (
            "\n--- SUMMARY INSIGHTS ---\n"
            "This report provides a detailed risk score breakdown per category and the rationale behind each rating. "
            "It explains how the provider's operational, financial, regulatory, cybersecurity, and reputation domains "
            "contribute to the overall score.\n\n"
            "Example questions that can be answered using this context:\n"
            "- What is the provider's overall risk?\n"
            "- Show the risk score breakdown.\n"
            "- Explain the reasoning behind the cybersecurity risk score.\n"
            "- How has the risk changed over time?\n"
        )

        # === ✅ Embed risk summary text into FAISS for retrieval ===
        provider_dir = Path("app/data/faiss_store") / provider_id
        provider_dir.mkdir(parents=True, exist_ok=True)

        index_file = provider_dir / f"{provider_id}.index"
        if index_file.exists():
            index_file.unlink()
            print(f"♻️ Cleared old FAISS index for {provider_id}")

        try:
            vectors = embed_texts([text_summary])
            faiss.normalize_L2(vectors)
            save_faiss_index(
                vectors=vectors,
                chunks=[text_summary],
                doc_id=provider_id,
                provider_dir=str(provider_dir)
            )
            print(f"💾 Embedded risk summary successfully for {provider_id}")
        except Exception as e:
            print(f"⚠️ FAISS embedding failed for {provider_id}: {e}")

        # --- Build response ---
        pre_snapshot = rec.get("pre_risk_snapshot", {}) or {"score": 0, "categories": {}, "timestamp": None}
        response = {
            "provider_id": provider_id,
            "risk_score": aggregated_score,
            "risk_level": rec.get("risk_level"),
            "categories": categories,
            "timestamp": timestamp,
            "pre_snapshot": pre_snapshot,
        }

        print(f"📢 Dashboard notified: Risk updated for {provider_id}")
        print(f"🧩 Embedded risk explanations and scores now searchable in RAG for provider {provider_id}")

        # ✅ Internal call → return plain dict
        if internal:
            return {"status": "ok", **response}

        # ✅ External API → return JSON
        return JSONResponse(content=response)

    except Exception as e:
        print(f"❌ Risk calculation failed for {provider_id}: {e}")
        if internal:
            return {"status": "error", "message": str(e)}
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
    score = risk.get("aggregated_score") or rec.get("risk_score")
    level = rec.get("risk_level") or "Unknown"
    categories = risk.get("category_scores", {}) or {}

    # --- ✅ Normalize category_scores if still numeric-only ---

    if isinstance(categories, dict):
        normalized = {}
        for cat, val in categories.items():
            if isinstance(val, (int, float)):
                normalized[cat] = {
                    "score": val,
                    "note": "No reasoning available (legacy or numeric-only record)."
                }
            elif isinstance(val, dict):
                normalized[cat] = {
                    "score": val.get("score", 0),
                    "note": val.get("note", val.get("reason", "No reasoning provided."))
                }
            else:
                normalized[cat] = {
                    "score": 0,
                    "note": "Invalid category value format."
                }
        categories = normalized


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

@router.get("/debug/{provider_id}")
async def debug_faiss(provider_id: str, verbose: bool = False):
    """
    Inspect FAISS index for a given provider.
    Returns summary of stored vectors and optional text preview.
    """
    from app.rag.vector_store_faiss import inspect_index

    try:
        result = inspect_index(provider_id, verbose=verbose)
        return {"status": "ok", "provider_id": provider_id, **result}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No FAISS index found for this provider")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 4️⃣ RESUBMIT RISK WITH SELECTED CHAT MESSAGES
# ============================================================
@router.post("/resubmit/{provider_id}")
async def resubmit_risk(provider_id: str):
    """
    Recalculate risk by injecting selected chat messages under doc_summary.
    Does NOT regenerate watchlists. Lightweight recomputation.
    """

    from app.services.application_store import load_applications, save_all
    from app.risk.payload_builder import build_model_payload
    from app.risk.orchestrator import convert_payload_to_text_prompt
    from app.risk.scoring import compute_scores_from_watchlists
    from app.services.risk_model_client import call_risk_model
    import json
    from datetime import datetime

    # ------------------------------------------------------------
    # 1️⃣ Load provider + messages
    # ------------------------------------------------------------
    apps = load_applications()
    record = next(
        (r for r in apps 
         if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None
    )
    if not record:
        return JSONResponse({"error": "Provider not found"}, status_code=404)

    messages = record.get("messages", [])
    selected = [
        (m["text"] if isinstance(m, dict) else str(m))
        for m in messages
        if (m.get("use_for_risk") if isinstance(m, dict) else False)
    ]

    # ------------------------------------------------------------
    # 2️⃣ Build normal base payload (watchlist-driven)
    # ------------------------------------------------------------
    payload = build_model_payload(provider_id)

    # ------------------------------------------------------------
    # 3️⃣ Insert selected messages into doc_summary
    # ------------------------------------------------------------
    existing_summary = payload.get("doc_summary") or ""

    if selected:
        analyst_notes = "\n\nAdditional Analyst Notes:\n"
        for msg in selected:
            cleaned = msg.replace('"', "'")
            analyst_notes += f"- {cleaned}\n"
    else:
        analyst_notes = ""

    full_doc_summary = existing_summary + analyst_notes
    payload["doc_summary"] = full_doc_summary

    print("\n==== DOC SUMMARY AFTER RESUBMIT ====")
    print(full_doc_summary)
    print("====================================\n")

    # ------------------------------------------------------------
    # 4️⃣ Convert payload → YAML text → call fine-tuned model
    # ------------------------------------------------------------
    text_prompt = convert_payload_to_text_prompt(payload)

    print("[RESUBMIT] Calling risk model with prompt length:", len(text_prompt))

    # ⭐ FIX: call model synchronously
    raw_model = call_risk_model(
        text_prompt,
        model_name="gpt-4o-mini-2024-07-18-risk-eval-v2"
    )

    if isinstance(raw_model, str):
        try:
            model_output = json.loads(raw_model)
        except:
            model_output = {}
    else:
        model_output = raw_model or {}

    # ------------------------------------------------------------
    # 5️⃣ Compute deterministic backend scores (unchanged)
    # ------------------------------------------------------------
    det_scores = compute_scores_from_watchlists(payload["watchlist_categories"])

    final_categories = {}
    model_expl = model_output.get("category_explanations", {})
    model_cat_scores = model_output.get("category_scores", {})

    for cat, score in det_scores.items():
        wl_note = next(
            (c["note"] for c in payload["watchlist_categories"] if c["category"] == cat),
            ""
        )

        if cat in model_expl:
            note = model_expl[cat]
        elif cat in model_cat_scores:
            mc = model_cat_scores[cat]
            note = mc.get("note", wl_note) if isinstance(mc, dict) else wl_note
        else:
            note = wl_note or "No explanation available."

        final_categories[cat] = {"score": score, "note": note}

    # ------------------------------------------------------------
    # ⭐ 6️⃣ Deterministic adjustments based on analyst notes
    # ------------------------------------------------------------
    lower_notes = full_doc_summary.lower()

    # 🔥 Boost reputation score for serious misconduct keywords
    REPUTATION_KEYWORDS = [
        "misconduct", "fraud", "scam", "abuse",
        "harassment", "illegal", "criminal",
        "patient harm", "negligence", "safety violation"
    ]

    if any(k in lower_notes for k in REPUTATION_KEYWORDS):
        print("🔥 Reputation keyword detected — boosting reputation +25")
        final_categories["reputation"]["score"] = min(
            final_categories["reputation"]["score"] + 25,
            100
        )
        final_categories["reputation"]["note"] += " (Analyst flagged serious reputation concerns.)"

    # optional operational bump
    if any(k in lower_notes for k in ["negligence", "mismanagement", "unsafe"]):
        print("🔥 Operational keyword detected — boosting operational +15")
        final_categories["operational"]["score"] = min(
            final_categories["operational"]["score"] + 15,
            100
        )
        final_categories["operational"]["note"] += " (Analyst identified operational concerns.)"

    # ------------------------------------------------------------
    # 7️⃣ Final aggregated score + risk level
    # ------------------------------------------------------------
    #aggregated_score = round(
    #    sum(v["score"] for v in final_categories.values()) / len(final_categories),
    #    1
    #)
    # ============================================================
    # ⭐ APPLY WEIGHTED SCORE IN RESUBMIT
    # ============================================================
    WEIGHTS = {
        "reputation": 0.25,
        "regulatory": 0.20,
        "operational": 0.15,
        "financial": 0.15,
        "cybersecurity": 0.10,
        "data_privacy": 0.10,
        "supplychain": 0.05,
    }

    weighted_sum = 0.0
    total_weight = 0.0

    for cat, data in final_categories.items():
        score = data.get("score", 0)
        weight = WEIGHTS.get(cat, 0)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight > 0:
        aggregated_score = round(weighted_sum / total_weight, 1)
    else:
        aggregated_score = 0


    if aggregated_score >= 60:
        risk_level = "High"
    elif aggregated_score >= 30:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    timestamp = datetime.utcnow().isoformat()

    # ------------------------------------------------------------
    # 8️⃣ Save updated record
    # ------------------------------------------------------------
    record.setdefault("risk", {})
    record["risk"]["aggregated_score"] = aggregated_score
    record["risk"]["risk_level"] = risk_level
    record["risk"]["category_scores"] = final_categories
    record["risk"]["updated_at"] = timestamp
    record["risk_status"] = "Completed"

    record.setdefault("history", []).append({
        "event": "Risk Re-submitted with Analyst Notes",
        "timestamp": timestamp,
        "note": f"Risk updated after including {len(selected)} chat messages."
    })

    save_all(apps)

    # ------------------------------------------------------------
    # 9️⃣ Return updated snapshot
    # ------------------------------------------------------------
    return JSONResponse({
        "provider_id": provider_id,
        "aggregated_score": aggregated_score,
        "risk_level": risk_level,
        "categories": final_categories,
        "timestamp": timestamp,
        "notes_used": selected,
        "doc_summary": full_doc_summary,
    })




@router.post("/chat/toggle/{provider_id}")
async def toggle_message(provider_id: str, message_id: str, use_for_risk: bool):
    apps = load_applications()
    rec = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None
    )

    if not rec:
        return {"error": "Provider not found"}

    for msg in rec.get("messages", []):
        if msg["id"] == message_id:
            msg["use_for_risk"] = use_for_risk

    save_all(apps)
    return {"status": "ok", "message_id": message_id, "use_for_risk": use_for_risk}
