# app/routes/review.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.services.application_store import load_applications, upsert_application
from datetime import datetime

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/review/{application_id}", response_class=HTMLResponse)
async def review_application(request: Request, application_id: str):
    """Render detailed review page for a single provider application."""
    apps = load_applications()
    app_record = next((a for a in apps if a.get("id") == application_id or a.get("application_id") == application_id), None)

    if not app_record:
        return HTMLResponse(f"<h3>❌ Application {application_id} not found.</h3>", status_code=404)

    return templates.TemplateResponse(
        "application_review.html",
        {"request": request, "application": app_record}
    )


@router.post("/review/{application_id}/accept")
async def accept_application(application_id: str):
    """Approve the application and update its status."""
    apps = load_applications()
    for app in apps:
        if app.get("id") == application_id:
            app["status"] = "Approved"
            app["history"] = app.get("history", [])
            app["history"].append({"event": "Approved", "timestamp": datetime.utcnow().isoformat()})
            upsert_application(app)
            break
    return RedirectResponse(url="/upload/upload-form", status_code=303)


@router.post("/review/{application_id}/deny")
async def deny_application(application_id: str, reason: str = Form(...)):
    """Reject the application with a reason."""
    apps = load_applications()
    for app in apps:
        if app.get("id") == application_id:
            app["status"] = "Denied"
            app["denial_reason"] = reason
            app["history"] = app.get("history", [])
            app["history"].append({"event": "Denied", "reason": reason, "timestamp": datetime.utcnow().isoformat()})
            upsert_application(app)
            break
    return RedirectResponse(url="/upload/upload-form", status_code=303)
