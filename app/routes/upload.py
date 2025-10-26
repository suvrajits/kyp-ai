# app/routes/upload.py

from fastapi import APIRouter, File, UploadFile, HTTPException
from app.services.document_ai import analyze_document
from app.services.parser import parse_provider_license

router = APIRouter()

@router.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    if file.content_type not in ["application/pdf", "image/png", "image/jpeg"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, PNG, or JPEG are supported.")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # 🔍 Step 1: Analyze document with Azure AI
        extracted = analyze_document(contents)

        # 🧠 Step 2: Parse fields from raw KV output
        structured = parse_provider_license(extracted)

        # 📦 Step 3: Return response with waterfall flow hint
        return {
            "filename": file.filename,
            "content_type": file.content_type,
            "raw_extracted": extracted,
            "structured_fields": structured,
            "next_step": "/match",  # 🧭 frontend should redirect to match screen with structured_fields
            "message": "Extraction complete. Review the fields and click 'Next' to match against the registry."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document analysis failed: {str(e)}")
