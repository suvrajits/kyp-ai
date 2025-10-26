# app/routes/match.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.registry_matcher import match_provider

router = APIRouter()

# 📦 Define expected fields coming from the structured analyzer
class ProviderProfile(BaseModel):
    provider_name: str
    license_number: str
    specialty: Optional[str] = None
    issuing_authority: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None


@router.post("/match")
async def match_provider_profile(profile: ProviderProfile):
    try:
        # ✅ Unpack the tuple (match, score)
        matched_record, confidence = match_provider(profile.dict())

        return {
            "input_profile": profile.dict(),
            "matched_registry_record": matched_record,
            "match_confidence": confidence,
            "status": "Matched" if confidence >= 0.8 else "Needs Review",
            "next_step": "/generate_trust_card"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registry match failed: {str(e)}")
