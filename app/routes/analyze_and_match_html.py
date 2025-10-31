# app/routes/analyze_and_match_html.py

from fastapi import APIRouter, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
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
        # 3️⃣ Match against registry (now weighted + per-field)
        # ----------------------------------------------------------
        match_entry, match_data = match_provider(structured)
        match_percent = match_data.get("match_percent", 0.0)
        confidence = match_percent / 100.0
        recommendation = match_data.get("recommendation", "Unknown")

        # Determine status based on thresholds
        if match_percent >= 90:
            status = "Matched"
        elif match_percent >= 75:
            status = "Needs Review"
        else:
            status = "Unverified"

        # ----------------------------------------------------------
        # 4️⃣ Generate TEMP-ID and persist record
        # ----------------------------------------------------------
        application_id = generate_temp_id()
        record = {
            "id": application_id,
            "application_id": application_id,
            "provider": structured,
            "status": "New",
            "confidence": confidence,
            "match_percent": match_percent,
            "match_result": match_data,             # ✅ full per-field detail
            "match_explanation": match_data.get("per_field", {}),
            "match_recommendation": recommendation,
            "created_at": datetime.utcnow().isoformat(),
            "documents": [],
        }

        upsert_application(record)
        print(f"💾 Application {application_id} saved successfully with {match_percent}% match.")

        # ----------------------------------------------------------
        # 5️⃣ Cache latest state (used by dashboard & trust card)
        # ----------------------------------------------------------
        request.app.state.latest_structured = structured
        request.app.state.latest_matched = match_entry
        request.app.state.latest_match_data = match_data
        request.app.state.latest_confidence = confidence
        request.app.state.latest_status = status

        # ----------------------------------------------------------
        # 6️⃣ Redirect to review screen
        # ----------------------------------------------------------
        print(f"➡️ Redirecting analyst to review application {application_id}")
        return RedirectResponse(url=f"/review/{application_id}", status_code=303)

    except Exception as e:
        print(f"❌ Error in analyze_and_match_html: {e}")
        return HTMLResponse(f"<h3>❌ Analyze/Match failed:</h3><pre>{str(e)}</pre>", status_code=500)
