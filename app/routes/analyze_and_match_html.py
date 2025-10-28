# app/routes/analyze_and_match_html.py

from fastapi import APIRouter, Request, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime

# Core AI services
from app.services.document_ai import analyze_document
from app.services.parser import parse_provider_license
from app.services.registry_matcher import match_provider

# Reuse utilities
from app.routes.upload import generate_temp_id
from app.services.application_store import upsert_application  # ✅ centralized persistence

router = APIRouter()

# --------------------------------------------------------------------
# 📁 Paths
# --------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --------------------------------------------------------------------
# 🌐 Routes
# --------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page: upload form + applications grid."""
    return templates.TemplateResponse("upload_form.html", {"request": request})


@router.post("/analyze-and-match-html", response_class=HTMLResponse)
async def analyze_and_match_html(request: Request, file: UploadFile = File(...)):
    """
    Upload a provider license, run Document AI + parse, match against registry,
    persist/refresh the provider record (assign TEMP-ID if new),
    and render the Provider Verification Summary.
    """
    try:
        # ----------------------------------------------------------
        # 1️⃣ Read uploaded file
        # ----------------------------------------------------------
        contents = await file.read()
        if not contents:
            return HTMLResponse("<h3>❌ Uploaded file is empty.</h3>", status_code=400)

        # ----------------------------------------------------------
        # 2️⃣ Run Azure Document Intelligence + Parser
        # ----------------------------------------------------------
        extracted = analyze_document(contents)
        structured = parse_provider_license(extracted) or {}

        # Normalize key fields to avoid NoneType issues
        for k in ("provider_name", "license_number", "issuing_authority", "registration_id"):
            structured[k] = (structured.get(k) or "").strip()

        # ----------------------------------------------------------
        # 3️⃣ Match against registry (fuzzy)
        # ----------------------------------------------------------
        match_result, confidence = match_provider(structured)
        status = "Matched" if confidence >= 0.80 else "Needs Review"

        # ----------------------------------------------------------
        # 4️⃣ Generate TEMP-ID and persist record
        # ----------------------------------------------------------
        application_id = generate_temp_id()
        record = {
            "application_id": application_id,
            "provider": structured,
            "status": "Under Review",
            "confidence": confidence or 0.0,
            "created_at": datetime.utcnow().isoformat(),
            "documents": [],
        }

        upsert_application(record)  # ✅ saves to app/data/applications.json

        print(f"💾 Application {application_id} saved successfully.")

        # ----------------------------------------------------------
        # 5️⃣ Cache latest state (used by trust card, dashboard)
        # ----------------------------------------------------------
        request.app.state.latest_structured = structured
        request.app.state.latest_matched = match_result
        request.app.state.latest_confidence = confidence
        request.app.state.latest_status = status

        # ----------------------------------------------------------
        # 6️⃣ Render result.html summary
        # ----------------------------------------------------------
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "filename": file.filename,
                "structured": structured,
                "matched": match_result,
                "confidence": confidence,
                "status": status,
                "application_id": application_id,
            },
        )

    except Exception as e:
        print(f"❌ Error in analyze_and_match_html: {e}")
        return HTMLResponse(f"<h3>❌ Analyze/Match failed:</h3><pre>{str(e)}</pre>", status_code=500)
