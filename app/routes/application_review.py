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

router = APIRouter()

# ✅ Templates path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ============================================================
# 🟢 1️⃣ Review Page – Display Application + Matching Summary
# ============================================================
@router.get("/review/{app_id}", response_class=HTMLResponse)
async def review_application(request: Request, app_id: str):
    """
    Render the application review page for an analyst.
    Displays structured provider data, match percent, and per-field comparison.
    """
    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None,
    )

    if not record:
        return HTMLResponse(f"<h3>❌ No application found for ID: {app_id}</h3>", status_code=404)

    # Workflow logic: analyst can only review "New" or "Pending"
    if record.get("status") not in ["New", "Pending", "Under Review"]:
        return RedirectResponse(f"/dashboard/view/{record.get('id')}", status_code=303)

    provider_struct = record.get("provider", {}) or {}

    # --- Registry Matching (safe retry) ---
    try:
        best_match_entry, match_result = match_provider(provider_struct, debug=False)
    except Exception as e:
        print(f"⚠️ Registry matching failed for {app_id}: {e}")
        best_match_entry = None
        match_result = {
            "match_percent": 0.0,
            "per_field": {},
            "recommendation": "Matcher error",
            "reason": str(e),
        }

    # --- Safely extract matching metrics ---
    match_percent = match_result.get("match_percent", 0.0)
    if not isinstance(match_percent, (float, int)):
        match_percent = 0.0

    recommendation = match_result.get("recommendation", "Unknown")
    per_field = match_result.get("per_field", {})

    # Add human-readable "status" to each field comparison
    for field, info in per_field.items():
        score = info.get("score", 0)
        if score >= 0.9:
            info["status"] = "✅ Match"
        elif score >= 0.75:
            info["status"] = "⚠️ Partial"
        else:
            info["status"] = "❌ Mismatch"

    print(f"🧾 Review {app_id}: {match_percent}% match ({recommendation})")

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
            "match_percent": round(match_percent, 1),
            "recommendation": recommendation,
            "per_field": per_field,
            "best_match_entry": best_match_entry,
        },
    )


# ============================================================
# 🟢 2️⃣ Accept Application → Move to Provider Stage
# ============================================================
@router.post("/review/{app_id}/accept")
async def accept_application(request: Request, app_id: str):
    """
    Accepts an application, promotes TEMP-ID → APP-ID,
    builds FAISS index for license data, and redirects to dashboard.
    """
    from app.rag.ingest import embed_texts
    from app.rag.vector_store_faiss import save_faiss_index
    import faiss

    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None,
    )
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    # 🚧 Prevent double acceptance
    if record.get("id", "").startswith("APP-"):
        print(f"⚠️ Application {app_id} already promoted → {record['id']}")
        return RedirectResponse(url=f"/dashboard/view/{record['id']}", status_code=303)

    new_app_id = generate_app_id()
    print(f"🔁 Promoting {app_id} → {new_app_id}")

    # Move FAISS directory if present
    old_faiss_dir = Path("app/data/faiss_store") / app_id
    new_faiss_dir = Path("app/data/faiss_store") / new_app_id
    try:
        if old_faiss_dir.exists():
            move(str(old_faiss_dir), str(new_faiss_dir))
            print(f"📦 Moved FAISS data from {old_faiss_dir.name} → {new_faiss_dir.name}")
    except Exception as e:
        print(f"⚠️ Could not move FAISS folder ({app_id}): {e}")

    # Update record workflow state
    record["id"] = new_app_id
    record["application_id"] = new_app_id
    record["status"] = "Under Review"

    # Create FAISS embeddings
    try:
        provider = record.get("provider", {})
        if provider:
            text_data = "\n".join([f"{k}: {v}" for k, v in provider.items() if v])
            vectors = embed_texts([text_data])
            faiss.normalize_L2(vectors)
            provider_dir = Path("app/data/faiss_store") / new_app_id
            provider_dir.mkdir(parents=True, exist_ok=True)
            save_faiss_index(vectors=vectors, chunks=[text_data], doc_id=new_app_id, provider_dir=str(provider_dir))
            print(f"💾 FAISS index created for {new_app_id}")
    except Exception as e:
        print(f"❌ Failed FAISS creation for {new_app_id}: {e}")

    # Log + Save
    record.setdefault("history", []).append({
        "event": "Application Accepted & Promoted",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"Promoted from {app_id} → {new_app_id} and FAISS built."
    })

    save_all(apps)
    print(f"✅ Application {app_id} → {new_app_id} accepted successfully.")
    return RedirectResponse(url=f"/dashboard/view/{new_app_id}", status_code=303)


# ============================================================
# 🔴 3️⃣ Deny Application → Close It Out
# ============================================================
@router.post("/review/{app_id}/deny", response_class=HTMLResponse)
async def deny_application(request: Request, app_id: str, reason: str = Form(...)):
    """Marks an application as Denied and logs the reason."""
    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None,
    )
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    record["status"] = "Denied"
    record.setdefault("history", []).append({
        "event": f"Application Denied",
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    })

    save_all(apps)
    print(f"❌ Application {app_id} denied (Reason: {reason})")

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
            "message": f"❌ Application denied: {reason}",
        },
    )
