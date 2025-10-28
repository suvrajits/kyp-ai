# app/routes/trust_card.py

import io
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.services.trust_card_generator import generate_trust_card_pdf

router = APIRouter()

@router.get("/generate_trust_card")
async def generate_trust_card(request: Request):
    """
    Generates a downloadable PDF 'Trust Card' based on the most recent
    provider verification results stored in app.state.
    """
    try:
        structured = getattr(request.app.state, "latest_structured", None)
        matched = getattr(request.app.state, "latest_matched", None)
        confidence = getattr(request.app.state, "latest_confidence", None)
        status = getattr(request.app.state, "latest_status", None)

        # Validate
        if not structured or not matched:
            return {"error": "No analysis data found. Please upload and analyze a document first."}

        # ✅ Generate PDF bytes
        pdf_bytes = generate_trust_card_pdf(structured, matched, confidence, status)

        # ✅ Stream as downloadable PDF
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=trust_card.pdf"}
        )

    except Exception as e:
        return {"error": f"Failed to generate Trust Card: {str(e)}"}
