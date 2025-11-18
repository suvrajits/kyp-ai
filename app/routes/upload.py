# app/routes/upload.py
from fastapi import APIRouter, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from pathlib import Path
import json, os

# Core services
from app.services.document_ai import analyze_document
from app.services.parser import parse_provider_license
from app.services.application_store import append_message, load_applications, upsert_application
from app.services.id_utils import generate_temp_id  

router = APIRouter()

# ============================================================
# 🧩 Path Setup
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DATA_DIR = BASE_DIR / "app" / "data"
APPLICATIONS_FILE = DATA_DIR / "applications.json"
COUNTER_FILE = DATA_DIR / "application_counter.json"
os.makedirs(DATA_DIR, exist_ok=True)


# ============================================================
# 🔢 TEMP-ID Counter Helpers
# ============================================================
def load_counter() -> dict:
    """Load or initialize counter for TEMP-ID tracking."""
    if not COUNTER_FILE.exists():
        return {"last_temp_id": 0}
    try:
        return json.loads(COUNTER_FILE.read_text())
    except Exception:
        return {"last_temp_id": 0}


def save_counter(counter: dict):
    """Persist counter updates."""
    os.makedirs(COUNTER_FILE.parent, exist_ok=True)
    COUNTER_FILE.write_text(json.dumps(counter, indent=2))


def generate_temp_id() -> str:
    """Generate incremental TEMP-ID-### string."""
    counter = load_counter()
    counter["last_temp_id"] = counter.get("last_temp_id", 0) + 1
    save_counter(counter)
    return f"TEMP-ID-{counter['last_temp_id']:03d}"


# ============================================================
# 🟢 Upload Form + Provider Applications List
# ============================================================
@router.get("/upload-form", response_class=HTMLResponse)
async def upload_form(request: Request):
    """Main entry page — upload new license and view applications."""
    apps = load_applications()
    print(f"📂 Loaded applications from: {APPLICATIONS_FILE.resolve()}")
    print(f"📊 Current record count: {len(apps)}")

    latest_structured = getattr(request.app.state, "latest_structured", None)
    latest_confidence = getattr(request.app.state, "latest_confidence", None)
    latest_status = getattr(request.app.state, "latest_status", None)

    # Optional preview row for last analyzed document
    if latest_structured and isinstance(latest_structured, dict):
        temp_entry = {
            "id": "—",
            "provider": latest_structured,
            "status": latest_status or "Needs Review",
            "confidence": latest_confidence or 0.0,
            "created_at": "—",
        }
        license_no = latest_structured.get("license_number")
        if not any(
            app.get("provider", {}).get("license_number") == license_no for app in apps
        ):
            apps.insert(0, temp_entry)

    sorted_apps = sorted(apps, key=lambda x: x.get("created_at", ""), reverse=True)
    print(f"📘 Showing {len(sorted_apps)} provider record(s) in upload form.")

    return templates.TemplateResponse(
        "upload_form.html",
        {"request": request, "providers": sorted_apps},
    )


# ============================================================
# 🟣 Handle License Upload & Parsing
# ============================================================
@router.post("/analyze")
async def analyze_file(request: Request, file: UploadFile = File(...)):
    """
    Uploads a license file, extracts structured fields,
    and stores results persistently with a TEMP-ID if not yet approved.
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")
    if file.content_type not in ["application/pdf", "image/png", "image/jpeg"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF, PNG, or JPEG are supported.",
        )

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # --- Step 1: Document AI + Parsing ---
        extracted = analyze_document(contents)
        structured = parse_provider_license(extracted)

        # --- Step 2: Generate TEMP-ID ---
        temp_id = generate_temp_id()
        print(f"🆕 Generated TEMP-ID: {temp_id}")

        # --- Step 3: Build new record ---
        record = {
            "id": temp_id,  # grid-compatible
            "application_id": temp_id,  # backend-compatible
            "provider": structured,
            "status": "Under Review",  # default state
            "confidence": 0.0,
            "created_at": datetime.utcnow().isoformat(),
            "history": [
                {"event": "Created", "timestamp": datetime.utcnow().isoformat()}
            ],
            "messages": [],
            "documents": [],
        }

        # --- Step 4: Save using robust persistence helper ---
        upsert_application(record)
        print(f"💾 Application {temp_id} saved successfully.")

        # --- Step 5: Update runtime state for dashboard preview ---
        request.app.state.latest_structured = structured
        request.app.state.latest_confidence = 0.0
        request.app.state.latest_status = "Under Review"

        # --- Step 6: Respond to frontend ---
        return {
            "filename": file.filename,
            "application_id": temp_id,
            "structured_fields": structured,
            "message": f"✅ Extraction complete. Assigned temporary ID {temp_id}",
        }

    except Exception as e:
        print(f"❌ Unexpected error in /analyze: {e}")
        raise HTTPException(status_code=500, detail=f"Document analysis failed: {str(e)}")
