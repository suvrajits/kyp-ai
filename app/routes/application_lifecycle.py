# app/routes/application_lifecycle.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
from enum import Enum
from typing import Dict, Any

from app.services.application_store import (
    load_applications, save_all, upsert_application_record, find_by_id, append_application
)

router = APIRouter(prefix="/applications", tags=["applications"])

def _now_iso():
    return datetime.utcnow().isoformat()

class ApplicationState(str, Enum):
    UNDER_REVIEW = "Under Review"
    REQUEST_INFO = "Request Info"
    ACCEPTED = "Application Accepted"
    REJECTED = "Application Rejected"

def _ensure_history(rec: Dict[str, Any]) -> None:
    if "history" not in rec:
        rec["history"] = []

def _append_history(rec: Dict[str, Any], event: str) -> None:
    _ensure_history(rec)
    rec["history"].append({"event": event, "timestamp": _now_iso()})

# ----------------------
# Utilities
# ----------------------
def _assign_id_if_missing(rec: Dict[str, Any], generate_id_fn) -> str:
    """
    Ensure record has 'id' (used by UI). Caller may supply a generator function.
    """
    if not rec.get("id"):
        # fallback to application_id if present
        if rec.get("application_id"):
            rec["id"] = rec["application_id"]
        else:
            rec["id"] = generate_id_fn()
    return rec["id"]

# We'll import your existing TEMP-ID generator from upload module to keep the sequence
try:
    from app.routes.upload import generate_temp_id as _generate_temp_id
except Exception:
    # fallback simple generator (should not be used long-term)
    _generate_temp_id = lambda: f"TEMP-ID-{int(datetime.utcnow().timestamp())%100000}"

# ----------------------
# Routes
# ----------------------

@router.get("/", response_class=JSONResponse)
def list_applications():
    apps = load_applications()
    return JSONResponse({"count": len(apps), "results": apps})

@router.get("/{app_id}", response_class=JSONResponse)
def get_application(app_id: str):
    rec = find_by_id(app_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return JSONResponse(rec)

@router.post("/{app_id}/accept", response_class=JSONResponse)
def accept_application(app_id: str):
    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    rec["status"] = ApplicationState.ACCEPTED.value
    _append_history(rec, "Accepted")
    # ensure id exists before saving
    if not rec.get("id"):
        rec["id"] = app_id
    upsert_application_record(rec)
    return JSONResponse({"message": "Application accepted", "id": rec["id"]})

@router.post("/{app_id}/reject", response_class=JSONResponse)
def reject_application(app_id: str, reason: str = ""):
    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    rec["status"] = ApplicationState.REJECTED.value
    _append_history(rec, "Rejected" + (f": {reason}" if reason else ""))
    upsert_application_record(rec)
    return JSONResponse({"message": "Application rejected", "id": rec.get("id")})

@router.post("/{app_id}/request-info", response_class=JSONResponse)
def request_info(app_id: str, payload: Dict[str, str] = None):
    """
    Request info from provider.
    payload: { "message": "Please upload renewal certificate" }
    This stores the message in `messages` array and updates status to REQUEST_INFO.
    """
    payload = payload or {}
    message = payload.get("message") if isinstance(payload, dict) else str(payload or "")
    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")

    rec.setdefault("messages", []).append({
        "from": "Reviewer",
        "text": message or "Please provide additional documents",
        "timestamp": _now_iso()
    })
    rec["status"] = ApplicationState.REQUEST_INFO.value
    _append_history(rec, "Requested Info")
    upsert_application_record(rec)
    return JSONResponse({"message": "Request sent", "id": rec.get("id")})

@router.post("/{app_id}/message", response_class=JSONResponse)
def post_message(app_id: str, payload: Dict[str, str]):
    """
    Generic message endpoint for Reviewer or Provider.
    payload: {"from": "Provider"|"Reviewer", "text": "..." }
    """
    if not payload or "text" not in payload:
        raise HTTPException(status_code=400, detail="Missing message text")
    who = payload.get("from", "Provider")
    text = payload.get("text")

    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")

    rec.setdefault("messages", []).append({"from": who, "text": text, "timestamp": _now_iso()})
    # If provider responds, we may automatically re-run screening (not implemented here)
    _append_history(rec, f"Message from {who}")
    upsert_application_record(rec)
    return JSONResponse({"message": "Message stored", "id": rec.get("id")})

@router.post("/{app_id}/update-status", response_class=JSONResponse)
def update_status(app_id: str, payload: Dict[str, str]):
    """
    Generic status update by admin: payload { "status": "<state>", "note": "..." }
    Acceptable states: Under Review, Request Info, Application Accepted, Application Rejected
    """
    if not payload or "status" not in payload:
        raise HTTPException(status_code=400, detail="Missing status")
    new_status = payload.get("status")
    if new_status not in [s.value for s in ApplicationState]:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")

    apps = load_applications()
    rec = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")

    rec["status"] = new_status
    note = payload.get("note")
    _append_history(rec, f"Status changed to {new_status}" + (f": {note}" if note else ""))
    upsert_application_record(rec)
    return JSONResponse({"message": "Status updated", "id": rec.get("id")})
