# app/routes/trust_card.py

import io
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from app.services.trust_card_generator import generate_trust_card_pdf
from app.services.application_store import load_applications

router = APIRouter()


@router.get("/generate_trust_card")
async def generate_trust_card(request: Request):
    """
    Generates a downloadable PDF 'Trust Card' based on the most recent
    provider verification results.
    - Uses app.state if available (most recent analysis)
    - Falls back to the latest accepted/under-review provider from applications.json
    """
    try:
        # 1️⃣ Try in-memory state (most recent analysis)
        structured = getattr(request.app.state, "latest_structured", None)
        matched = getattr(request.app.state, "latest_matched", None)
        confidence = getattr(request.app.state, "latest_confidence", None)
        status = getattr(request.app.state, "latest_status", None)

        # 2️⃣ If nothing found, fallback to latest application record
        if not structured or not matched:
            apps = load_applications()
            if not apps:
                return JSONResponse(
                    {"error": "No application data found. Please analyze or accept one first."},
                    status_code=404
                )

            # Find latest accepted/under-review provider
            latest = next(
                (
                    a for a in sorted(apps, key=lambda x: x.get("created_at", ""), reverse=True)
                    if a.get("status") in ["Under Review", "Approved", "Application Accepted"]
                ),
                None
            )

            if not latest:
                return JSONResponse(
                    {"error": "No analyzed or accepted provider found to generate trust card."},
                    status_code=404
                )

            structured = latest.get("provider", {})
            matched = latest.get("provider", {})
            confidence = latest.get("confidence", 0.0)
            status = latest.get("status", "Under Review")
            print(f"📂 Using fallback from latest application: {latest.get('application_id')}")

        # 3️⃣ Generate Trust Card PDF
        pdf_bytes = generate_trust_card_pdf(
            structured=structured,
            matched=matched,
            confidence=confidence,
            status=status,
        )

        # 4️⃣ Return streaming PDF response
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=trust_card.pdf"},
        )

    except Exception as e:
        print(f"❌ Error generating Trust Card: {e}")
        return JSONResponse({"error": f"Failed to generate Trust Card: {str(e)}"}, status_code=500)
