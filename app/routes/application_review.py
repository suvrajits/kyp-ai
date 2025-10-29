# app/routes/application_review.py

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.services.application_store import load_applications, save_all

from datetime import datetime
from pathlib import Path
from app.services.id_utils import generate_app_id


router = APIRouter()

# ✅ Templates path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ============================================================
# 🟢 1️⃣ Review Page – Display Application for Analyst
# ============================================================
@router.get("/review/{app_id}", response_class=HTMLResponse)
async def review_application(request: Request, app_id: str):
    """Render the application review page for a 'New' application."""
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)

    if not record:
        return HTMLResponse(f"<h3>❌ No application found for ID: {app_id}</h3>", status_code=404)

    # Only allow review if it's still 'New'
    if record.get("status") not in ["New", "Pending"]:
        return RedirectResponse(f"/dashboard/view/{app_id}", status_code=303)

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
        },
    )


# ============================================================
# 🟢 2️⃣ Accept Application → Move to Provider Stage
# ============================================================
@router.post("/review/{app_id}/accept")
async def accept_application(request: Request, app_id: str):
    """
    Accept an incoming application.
    Promotes TEMP-ID → APP-ID and moves it to the provider stage.
    """
    apps = load_applications()
    record = None

    for rec in apps:
        if rec.get("id") == app_id or rec.get("application_id") == app_id:
            record = rec
            break

    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    # ✅ Promote ID from TEMP-ID → APP-ID
    if str(record.get("id", "")).startswith("TEMP-ID"):
        new_app_id = generate_app_id()
        print(f"🔁 Promoting {app_id} → {new_app_id}")
        record["id"] = new_app_id
        record["application_id"] = new_app_id

    # ✅ Update status & log
    record["status"] = "Under Review"
    record.setdefault("history", []).append({
        "event": "Application Accepted & Promoted",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"Promoted from {app_id} → {record['id']}"
    })

    # ✅ Persist change
    save_all(apps)
    print(f"✅ Application {app_id} promoted → {record['id']} and moved to 'Under Review'")

    # ✅ Redirect to the new dashboard page
    return RedirectResponse(url=f"/dashboard/view/{record['id']}", status_code=303)



# ============================================================
# 🔴 3️⃣ Deny Application → Close It Out
# ============================================================
@router.post("/review/{app_id}/deny", response_class=HTMLResponse)
async def deny_application(request: Request, app_id: str, reason: str = Form(...)):
    """
    Deny an unfit application.
    Sets status → 'Denied' and logs reason.
    """
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    record["status"] = "Denied"
    record.setdefault("history", []).append({
        "event": f"Application Denied ({reason})",
        "timestamp": datetime.utcnow().isoformat()
    })

    save_all(apps)
    print(f"❌ Application {app_id} denied. Reason: {reason}")

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
            "message": f"❌ Application denied: {reason}",
        },
    )
