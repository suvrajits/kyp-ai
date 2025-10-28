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
    if APPLICATIONS_FILE.exists():
        try:
            return json.loads(APPLICATIONS_FILE.read_text())
        except Exception:
            return []
    return []


def save_applications(records: list):
    APPLICATIONS_FILE.write_text(json.dumps(records, indent=2))


def provider_already_exists(provider: dict, existing: list) -> dict | None:
    """Return existing record if provider already approved."""
    key_fields = ["license_number", "registration_id", "provider_name"]
    for rec in existing:
        p = rec.get("provider", {})
        if any(
            provider.get(k) and provider.get(k) == p.get(k)
            for k in key_fields
        ):
            return rec
    return None


# ---------- Approve / Create Application ----------
@router.post("/create-application")
async def create_application(request: Request, provider_data: str = Form(...)):
    """
    Create new provider application (persistent JSON storage).
    If provider already exists, auto-ingest its FAISS profile if missing.
    """
    from app.rag.ingest import embed_texts
    from app.rag.vector_store_faiss import save_faiss_index
    import numpy as np, faiss
    from pathlib import Path

    try:
        provider = json.loads(provider_data)
    except Exception:
        provider = {}

    existing = load_applications()
    duplicate = provider_already_exists(provider, existing)

    # ✅ Handle already approved provider
    if duplicate:
        provider_id = duplicate["id"]
        provider_dir = Path("app/data/faiss_store") / provider_id
        provider_dir.mkdir(parents=True, exist_ok=True)
        index_files = list(provider_dir.glob("*.index"))

        # ✅ Auto-ingest provider info if FAISS data missing
        if not index_files:
            print(f"📘 Auto-ingesting FAISS data for existing provider {provider_id}")
            text_summary = " ".join([f"{k}: {v}" for k, v in duplicate["provider"].items()])
            vectors = embed_texts([text_summary])
            faiss.normalize_L2(vectors)
            save_faiss_index(vectors, [text_summary], doc_id="provider_profile", provider_dir=str(provider_dir))
        else:
            print(f"✅ FAISS index already exists for provider {provider_id}")

        return templates.TemplateResponse(
            "provider_dashboard.html",
            {
                "request": request,
                "app_id": provider_id,
                "provider": duplicate["provider"],
                "status": "Approved",
                "documents": duplicate.get("documents", []),
                "message": "ℹ️ This provider was already approved earlier.",
            },
        )

    # ✅ New provider approval path
    app_id = f"APP-{datetime.now().strftime('%Y%m%d')}-{random.randint(10000,99999)}"
    record = {
        "id": app_id,
        "provider": provider,
        "created_at": datetime.now().isoformat(),
        "status": "Approved",
        "documents": [],
    }
    existing.append(record)
    save_applications(existing)

    # ✅ Persist in app.state
    request.app.state.current_application = record

    # ✅ Auto-ingest provider info immediately on approval
    try:
        text_summary = " ".join([f"{k}: {v}" for k, v in provider.items()])
        vectors = embed_texts([text_summary])
        faiss.normalize_L2(vectors)

        provider_dir = Path("app/data/faiss_store") / app_id
        provider_dir.mkdir(parents=True, exist_ok=True)
        save_faiss_index(vectors, [text_summary], doc_id="provider_profile", provider_dir=str(provider_dir))
        print(f"✅ Embedded provider profile for {app_id}")
    except Exception as e:
        print(f"⚠️ Could not embed provider info: {e}")

    # ✅ Return dashboard
    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": provider,
            "status": "Approved",
            "documents": [],
            "message": "✅ Provider approved successfully and stored permanently.",
        },
    )


# ---------- View Existing Application ----------
@router.get("/view/{app_id}", response_class=HTMLResponse)
async def view_dashboard(request: Request, app_id: str):
    """Display provider details and uploaded document list."""
    apps = load_applications()
    record = next((r for r in apps if r["id"] == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ No provider found for App ID: {app_id}</h3>", status_code=404)

    provider = record["provider"]
    documents = record.get("documents", [])

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": provider,
            "documents": documents,
            "status": record.get("status", "Approved"),
            "message": "📄 Dashboard refreshed.",
        },
    )


# ---------- Reject Application ----------
@router.post("/reject-application")
async def reject_application(request: Request, rejection_reason: str = Form(...)):
    """Reject provider license and record reason (in-memory only for now)."""
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
