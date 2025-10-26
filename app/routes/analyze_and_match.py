# app/routes/analyze_and_match.py

from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.document_ai import analyze_document
from app.services.parser import parse_provider_license
from app.services.registry_matcher import match_provider

router = APIRouter()


@router.post("/analyze-and-match")
async def analyze_and_match(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    if file.content_type not in ["application/pdf", "image/png", "image/jpeg"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF, PNG, or JPEG are supported."
        )

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Step 1: Extract raw fields and paragraphs
        raw_extracted = analyze_document(contents)

        # Step 2: Parse structured fields from key-value pairs
        structured_fields = parse_provider_license(raw_extracted)

        # Step 3: Match against mock registry
        matched_record, confidence = match_provider(structured_fields)

        return {
            "filename": file.filename,
            "content_type": file.content_type,
            "raw_extracted": raw_extracted,
            "structured_fields": structured_fields,
            "matched_registry_record": matched_record,
            "match_confidence": confidence,
            "status": "Matched" if confidence >= 0.8 else "Needs Review",
            "next_step": "/generate_trust_card"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analyze & match failed: {str(e)}")
