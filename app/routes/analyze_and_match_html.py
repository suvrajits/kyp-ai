# app/routes/analyze_and_match_html.py

from fastapi import APIRouter, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
import tempfile

# Core AI services
from app.services.parser import parse_provider_license
from app.services.registry_matcher import match_provider

# Reuse utilities
from app.routes.upload import generate_temp_id
from app.services.application_store import upsert_application  # centralized persistence

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
    Upload a provider license, extract structured fields using Azure Document Intelligence,
    match against registry, persist result, and redirect to the Review page.
    """
    temp_pdf_path = None
    try:
        # ----------------------------------------------------------
        # 1️⃣ Save uploaded file temporarily
        # ----------------------------------------------------------
        contents = await file.read()
        if not contents:
            return HTMLResponse("<h3>❌ Uploaded file is empty.</h3>", status_code=400)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contents)
            temp_pdf_path = tmp.name

        print(f"📂 Uploaded PDF saved to temporary path: {temp_pdf_path}")

        # ----------------------------------------------------------
        # 2️⃣ Extract fields using Azure Document Intelligence Parser
        # ----------------------------------------------------------
        print("🧠 Running Azure Document Intelligence model for field extraction...")
        structured = parse_provider_license(temp_pdf_path, debug=True)

        if not structured or not isinstance(structured, dict):
            return HTMLResponse("<h3>⚠️ No fields extracted from document.</h3>", status_code=422)

        # Normalize key identifiers
        for k in ("provider_name", "license_number", "licensing_authority_name"):
            structured[k] = (structured.get(k) or "").strip()

        # ----------------------------------------------------------
        # 3️⃣ Match against registry (for scoring only)
        # ----------------------------------------------------------
        print("🔍 Matching extracted fields against registry...")
        try:
            match_entry, match_result = match_provider(structured, debug=True)
        except TypeError:
            match_entry, match_result = match_provider(structured)

        # Defensive fallback — always ensure we have a dict
        if not isinstance(match_result, dict):
            print("⚠️ match_provider returned unexpected type, creating default match_result.")
            match_result = {
                "match_percent": 0.0,
                "per_field": {},
                "recommendation": "No Match Found"
            }

        # Extract match intelligence safely
        match_percent = match_result.get("match_percent", 0.0)
        if not isinstance(match_percent, (int, float)):
            match_percent = 0.0

        confidence = round(match_percent / 100.0, 2)
        recommendation = match_result.get("recommendation", "Unknown")

        # ✅ Application workflow status is always NEW
        workflow_status = "New"

        # ----------------------------------------------------------
        # 4️⃣ Persist record with both workflow + AI match metadata
        # ----------------------------------------------------------
        application_id = generate_temp_id()
        record = {
            "id": application_id,
            "application_id": application_id,
            "provider": structured,
            "status": workflow_status,  # workflow
            "confidence": confidence,   # AI similarity
            "match_percent": match_percent,
            "match_result": match_result,
            "match_explanation": match_result.get("per_field", {}),
            "match_recommendation": recommendation,
            "created_at": datetime.utcnow().isoformat(),
            "documents": [file.filename],
        }

        upsert_application(record)
        print(
            f"💾 Application {application_id} saved successfully."
            f" [Workflow: {workflow_status}, Match: {match_percent}%]"
        )

        # ----------------------------------------------------------
        # 5️⃣ Cache state (for dashboard/trust card)
        # ----------------------------------------------------------
        request.app.state.latest_structured = structured
        request.app.state.latest_matched = match_entry
        request.app.state.latest_match_data = match_result
        request.app.state.latest_confidence = confidence
        request.app.state.latest_status = workflow_status

        # ----------------------------------------------------------
        # 6️⃣ Redirect to Review screen
        # ----------------------------------------------------------
        print(f"➡️ Redirecting analyst to review application {application_id}")
        return RedirectResponse(url=f"/review/{application_id}", status_code=303)

    except Exception as e:
        print(f"❌ Error in analyze_and_match_html: {e}")
        return HTMLResponse(f"<h3>❌ Analyze/Match failed:</h3><pre>{str(e)}</pre>", status_code=500)

    finally:
        # Always cleanup temp file
        if temp_pdf_path and Path(temp_pdf_path).exists():
            try:
                Path(temp_pdf_path).unlink()
                print(f"🧹 Cleaned up temp file: {temp_pdf_path}")
            except Exception as cleanup_err:
                print(f"⚠️ Temp cleanup failed: {cleanup_err}")
