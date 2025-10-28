from fastapi import APIRouter, Request, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.services.document_ai import analyze_document
from app.services.parser import parse_provider_license
from app.services.registry_matcher import match_provider

# ---------------------------------------------------------------------
# Global state (used by trust_card.py)
# ---------------------------------------------------------------------
latest_structured = {}
latest_matched = {}
latest_confidence = 0.0
latest_status = ""

# ---------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------
router = APIRouter()

# Dynamically resolve absolute path to /templates
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------
# UI route: Upload page
# ---------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Displays the file upload form."""
    return templates.TemplateResponse("upload_form.html", {"request": request})


# ---------------------------------------------------------------------
# POST route: Analyze document + match against registry
# ---------------------------------------------------------------------
@router.post("/analyze-and-match-html", response_class=HTMLResponse)
async def analyze_and_match_html(request: Request, file: UploadFile = File(...)):
    """
    Uploads a provider license document, runs document AI extraction,
    parses fields, matches against registry, and renders the result.
    """

    # Read uploaded file
    contents = await file.read()

    # Run document AI extraction and parsing
    extracted = analyze_document(contents)
    structured = parse_provider_license(extracted)

    # Match against registry
    match_result, confidence = match_provider(structured)
    status = "Matched" if confidence >= 0.8 else "Needs Review"

    # ✅ Store in FastAPI app state instead of globals
    request.app.state.latest_structured = structured
    request.app.state.latest_matched = match_result
    request.app.state.latest_confidence = confidence
    request.app.state.latest_status = status

    # Render result page
    return templates.TemplateResponse("result.html", {
        "request": request,
        "filename": file.filename,
        "structured": structured,
        "matched": match_result,
        "confidence": confidence,
        "status": status
    })
