# app/routes/provider_dashboard.py

from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
from datetime import datetime
import json, random

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DATA_DIR = BASE_DIR / "app" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
APPLICATIONS_FILE = DATA_DIR / "applications.json"


# ---------- Utility Helpers ----------
def load_applications() -> list:
    """Load all persisted provider applications."""
    if APPLICATIONS_FILE.exists():
        try:
            return json.loads(APPLICATIONS_FILE.read_text())
        except Exception:
            return []
    return []


def save_applications(records: list):
    """Save all provider application records to disk."""
    APPLICATIONS_FILE.write_text(json.dumps(records, indent=2))


def provider_already_exists(provider: dict, existing: list) -> dict | None:
    """Detect duplicate providers by license, registration, or name."""
    key_fields = ["license_number", "registration_id", "provider_name"]
    for rec in existing:
        p = rec.get("provider", {})
        if any(provider.get(k) and provider.get(k) == p.get(k) for k in key_fields):
            return rec
    return None


# ---------- Create / Approve Provider Application ----------
@router.post("/create-application")
async def create_application(request: Request, provider_data: str = Form(...)):
    """
    Create or reuse a provider application.
    - If provider already exists, mark as ✅ 'Previously Approved'
    - If new, mark as 🩵 'Application Accepted'
    """
    from app.rag.ingest import embed_texts
    from app.rag.vector_store_faiss import save_faiss_index
    import numpy as np, faiss

    try:
        provider = json.loads(provider_data)
    except Exception:
        provider = {}

    existing = load_applications()
    duplicate = provider_already_exists(provider, existing)

    # 🟢 Existing Provider → Previously Approved
    if duplicate:
        provider_id = duplicate["id"]
        provider_dir = Path("app/data/faiss_store") / provider_id
        provider_dir.mkdir(parents=True, exist_ok=True)

        index_files = list(provider_dir.glob("*.index"))
        if not index_files:
            print(f"📘 Auto-ingesting FAISS data for existing provider {provider_id}")
            text_summary = " ".join([f"{k}: {v}" for k, v in duplicate["provider"].items()])
            vectors = embed_texts([text_summary])
            faiss.normalize_L2(vectors)
            save_faiss_index(
                vectors, [text_summary],
                doc_id="provider_profile",
                provider_dir=str(provider_dir)
            )
        else:
            print(f"✅ FAISS index already exists for provider {provider_id}")

        return templates.TemplateResponse(
            "provider_dashboard.html",
            {
                "request": request,
                "app_id": provider_id,
                "provider": duplicate["provider"],
                "status": "Application Accepted",
                "documents": duplicate.get("documents", []),
                "message": "ℹ️ This provider was already verified and approved earlier.",
            },
        )

    # 🩵 New Provider → Application Accepted
    app_id = f"APP-{datetime.now().strftime('%Y%m%d')}-{random.randint(10000,99999)}"
    record = {
        "id": app_id,
        "provider": provider,
        "created_at": datetime.now().isoformat(),
        "status": "Application Accepted",
        "documents": [],
    }
    existing.append(record)
    save_applications(existing)

    request.app.state.current_application = record

    # Auto-ingest provider info to FAISS
    try:
        text_summary = " ".join([f"{k}: {v}" for k, v in provider.items()])
        vectors = embed_texts([text_summary])
        faiss.normalize_L2(vectors)

        provider_dir = Path("app/data/faiss_store") / app_id
        provider_dir.mkdir(parents=True, exist_ok=True)
        save_faiss_index(
            vectors, [text_summary],
            doc_id="provider_profile",
            provider_dir=str(provider_dir)
        )
        print(f"✅ Embedded provider profile for {app_id}")
    except Exception as e:
        print(f"⚠️ Could not embed provider info: {e}")

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": provider,
            "status": "Application Accepted",
            "documents": [],
            "message": "✅ Provider application accepted successfully and stored permanently.",
        },
    )


# ---------- View Existing Application ----------
@router.get("/view/{app_id}", response_class=HTMLResponse)
async def view_dashboard(request: Request, app_id: str):
    """
    Display provider details and uploaded document list.
    Supports both permanent IDs (APP-...) and temporary IDs (TEMP-ID-...).
    Ensures legacy records load safely and UI fields remain consistent.
    """
    apps = load_applications()

    # ✅ Match by either `id` or `application_id`
    record = next(
        (
            r
            for r in apps
            if str(r.get("id")) == app_id or str(r.get("application_id")) == app_id
        ),
        None,
    )

    # ✅ Graceful handling if record is missing
    if not record:
        return HTMLResponse(
            f"<h3>❌ No provider found for Application ID: {app_id}</h3>",
            status_code=404,
        )

    # ✅ Normalize legacy records (some may lack `id`)
    if not record.get("id") and record.get("application_id"):
        record["id"] = record["application_id"]
    elif not record.get("application_id") and record.get("id"):
        record["application_id"] = record["id"]

    # ✅ Adjust display status for TEMP-ID applications
    display_status = record.get("status", "Under Review")
    if str(record["id"]).startswith("TEMP-ID") and display_status == "Application Accepted":
        display_status = "Under Review"

    # ✅ Defensive field population
    provider = record.get("provider", {}) or {}
    documents = record.get("documents", [])

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": record.get("id", app_id),
            "provider": provider,
            "documents": documents,
            "status": display_status,
            "message": "📄 Provider dashboard loaded successfully.",
        },
    )



# ---------- Reject Application ----------
@router.post("/reject-application")
async def reject_application(request: Request, rejection_reason: str = Form(...)):
    """Reject provider license and show reason."""
    rejection_entry = {
        "timestamp": datetime.now().isoformat(),
        "reason": rejection_reason,
    }
    request.app.state.last_rejection = rejection_entry

    return templates.TemplateResponse(
        "upload_form.html",
        {
            "request": request,
            "message": f"❌ Provider License Rejected. Reason: {rejection_reason}",
        },
    )


# ---------- Delete Document ----------
@router.post("/delete-document")
async def delete_document(request: Request, app_id: str = Form(...), filename: str = Form(...)):
    """Delete a specific uploaded document and related FAISS index."""
    import os

    apps = load_applications()
    record = next((r for r in apps if r["id"] == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ No provider found for App ID: {app_id}</h3>", status_code=404)

    provider_dir = Path("app/data/faiss_store") / app_id
    deleted_any = False

    if provider_dir.exists():
        for fname in os.listdir(provider_dir):
            if filename.split(".")[0] in fname:
                try:
                    os.remove(provider_dir / fname)
                    deleted_any = True
                    print(f"🗑️ Deleted {fname}")
                except Exception as e:
                    print(f"⚠️ Error deleting {fname}: {e}")

    # Update record
    record["documents"] = [d for d in record.get("documents", []) if d["filename"] != filename]
    save_applications(apps)

    msg = (
        f"✅ Deleted document '{filename}' and its FAISS index."
        if deleted_any else f"⚠️ No FAISS files found for '{filename}'."
    )

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": record["provider"],
            "documents": record["documents"],
            "status": record.get("status", "Application Accepted"),
            "message": msg,
        },
    )

@router.get("/upload-form", response_class=HTMLResponse)
async def upload_form(request: Request):
    """
    Display the provider license upload form + registry grid below it.
    """
    apps = load_applications()
    sorted_apps = sorted(apps, key=lambda x: x.get("created_at", ""), reverse=True)
    return templates.TemplateResponse(
        "upload_form.html",
        {
            "request": request,
            "providers": sorted_apps,
        },
    )
