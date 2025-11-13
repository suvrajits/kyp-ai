# app/routes/application_review.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.services.application_store import load_applications, save_all
from app.services.id_utils import generate_app_id
from app.services.registry_matcher import match_provider
from datetime import datetime
from pathlib import Path
from shutil import move
import asyncio

from app.risk.watchlist_simulator import CATEGORIES, simulate_watchlist_light
from app.routes.risk_router import calculate_provider_risk
from app.rag.ingest import embed_texts, save_faiss_index  # optional

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/review/{app_id}", response_class=HTMLResponse)
async def review_application(request: Request, app_id: str):
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ No application found for ID: {app_id}</h3>", status_code=404)

    if record.get("status") not in ["New", "Pending", "Under Review"]:
        return RedirectResponse(f"/dashboard/view/{record.get('id')}", status_code=303)

    provider_struct = record.get("provider", {}) or {}

    try:
        best_match_entry, match_result = match_provider(provider_struct, debug=False)
    except Exception as e:
        best_match_entry = None
        match_result = {"match_percent": 0.0, "per_field": {}, "recommendation": "Matcher error", "reason": str(e)}

    match_percent = match_result.get("match_percent", 0.0)
    if not isinstance(match_percent, (float, int)):
        match_percent = 0.0

    recommendation = match_result.get("recommendation", "Unknown")
    per_field = match_result.get("per_field", {})

    for field, info in per_field.items():
        score = info.get("score", 0)
        if score >= 0.9:
            info["status"] = "✅ Match"
        elif score >= 0.75:
            info["status"] = "⚠️ Partial"
        else:
            info["status"] = "❌ Mismatch"

    # --- Pre-risk snapshot (lightweight, in-memory only) ---
    async def simulate_pre_risk(provider):
        name = provider.get("provider_name")
        lic = provider.get("license_number")
        # call the lightweight simulator (does not write files)
        results = await asyncio.gather(*[simulate_watchlist_light(name, lic, c) for c in CATEGORIES])

        category_scores = {}
        for r in results:
            cat = r["category"]
            hits = r.get("entries", [])
            avg_sev = (sum(e.get("severity", 0.3) for e in hits) / max(1, len(hits))) if hits else 0.1
            category_scores[cat] = round(avg_sev * 100, 1)

        total = sum(category_scores.values()) / max(1, len(category_scores))
        return round(total, 1), category_scores

    pre_risk_score, pre_risk_categories = await simulate_pre_risk(provider_struct)

    record["pre_risk_snapshot"] = {
        "score": pre_risk_score,
        "categories": pre_risk_categories,
        "timestamp": datetime.utcnow().isoformat()
    }
    record.setdefault("history", []).append({
        "event": "Pre-Risk Snapshot Preserved",
        "score": pre_risk_score,
        "timestamp": datetime.utcnow().isoformat(),
        "note": "Stored for comparison against post-acceptance risk evaluation."
    })

    if "pre_risk_snapshot" in record:
        record["history"].append({
            "event": "Pre-Risk Snapshot Linked",
            "timestamp": datetime.utcnow().isoformat(),
            "note": "Preliminary risk snapshot linked to provider record for drift comparison."
        })

    # Save after adding pre-risk snapshot
    save_all(apps)

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
            "match_percent": round(match_percent, 1),
            "recommendation": recommendation,
            "per_field": per_field or {},
            "best_match_entry": best_match_entry or {},
            "pre_risk_score": pre_risk_score,
            "pre_risk_categories": pre_risk_categories,
        },
    )


@router.post("/review/{app_id}/accept")
async def accept_application(request: Request, app_id: str):
    from app.rag.ingest import embed_texts, save_faiss_index
    import faiss

    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    if record.get("id", "").startswith("APP-"):
        return RedirectResponse(url=f"/dashboard/view/{record['id']}", status_code=303)

    new_app_id = generate_app_id()

    # Move FAISS directory if present (keep existing behavior)
    old_faiss_dir = Path("app/data/faiss_store") / app_id
    new_faiss_dir = Path("app/data/faiss_store") / new_app_id
    try:
        if old_faiss_dir.exists():
            move(str(old_faiss_dir), str(new_faiss_dir))
    except Exception as e:
        print(f"⚠️ Could not move FAISS folder ({app_id}): {e}")

    # Update record id and workflow state
    record["id"] = new_app_id
    record["application_id"] = new_app_id
    record["status"] = "Under Review"

    # IMPORTANT: save the updated apps *before* triggering the async risk pipeline
    save_all(apps)

    # Build FAISS for provider profile (non-blocking error-safe)
    try:
        provider = record.get("provider", {})
        if provider:
            text_data = "\n".join([f"{k}: {v}" for k, v in provider.items() if v])
            vectors = embed_texts([text_data])
            faiss.normalize_L2(vectors)
            provider_dir = Path("app/data/faiss_store") / new_app_id
            provider_dir.mkdir(parents=True, exist_ok=True)
            save_faiss_index(
                vectors=vectors,
                chunks=[text_data],
                doc_id=new_app_id,
                provider_dir=str(provider_dir)
            )
    except Exception as e:
        print(f"❌ Failed FAISS creation for {new_app_id}: {e}")

    # Update history + risk state
    record.setdefault("history", []).append({
        "event": "Application Accepted & Promoted",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"Promoted from {app_id} → {new_app_id} and FAISS built."
    })
    record["risk_status"] = "Evaluating"
    record["risk_score"] = None
    record["risk_level"] = None

    # Persist the change (again to be safe)
    save_all(apps)

    print(f"🧠 Triggering async risk evaluation for {new_app_id} at {datetime.utcnow().isoformat()} ...")

    # Fire-and-forget risk pipeline — avoid duplicates using a trigger timestamp
    if record.get("risk_status") != "Evaluating" or not record.get("risk_triggered_at"):
        record["risk_status"] = "Evaluating"
        record["risk_triggered_at"] = datetime.utcnow().isoformat()
        save_all(apps)

        async def risk_pipeline(app_id_inner: str):
            try:
                await calculate_provider_risk(app_id_inner, internal=True)
            except Exception as e:
                print(f"❌ Risk pipeline failed for {app_id_inner}: {e}")

        asyncio.create_task(risk_pipeline(new_app_id))
        record.setdefault("history", []).append({
            "event": "Risk Evaluation Pipeline Triggered",
            "timestamp": datetime.utcnow().isoformat()
        })
        save_all(apps)
    else:
        print(f"⚠️ Risk evaluation already in progress for {new_app_id}")

    print(f"✅ Application {app_id} → {new_app_id} accepted successfully.")
    return RedirectResponse(url=f"/dashboard/view/{new_app_id}", status_code=303)


@router.post("/review/{app_id}/deny", response_class=HTMLResponse)
async def deny_application(request: Request, app_id: str, reason: str = Form(...)):
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    record["status"] = "Denied"
    record.setdefault("history", []).append({
        "event": f"Application Denied",
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    })
    record["risk_status"] = "N/A"
    record["risk_score"] = None
    record["risk_level"] = None
    save_all(apps)
    return RedirectResponse(url="/upload/upload-form", status_code=303)
