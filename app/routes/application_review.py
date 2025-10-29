# app/routes/application_review.py

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.services.application_store import load_applications, save_all

from datetime import datetime
from pathlib import Path

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
    Changes status → 'Under Review'
    and redirects to provider dashboard.
    """
    apps = load_applications()
    for rec in apps:
        if rec.get("id") == app_id or rec.get("application_id") == app_id:
            rec["status"] = "Under Review"
            rec.setdefault("history", []).append({
                "event": "Application Accepted",
                "timestamp": datetime.utcnow().isoformat()
            })
            break
    else:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    save_all(apps)
    print(f"✅ Application {app_id} moved to 'Under Review' (Provider Stage)")
    return RedirectResponse(url=f"/dashboard/view/{app_id}", status_code=303)


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
