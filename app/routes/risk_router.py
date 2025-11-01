# app/routes/risk_router.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pathlib import Path
import json

router = APIRouter(tags=["Risk Calculator"])

DATA_PATH = Path("app/data/applications.json")


@router.get("/risk/calc/{provider_id}")
async def calculate_provider_risk(provider_id: str):
    """
    Calculates a multi-category Provider Risk Index.
    Returns normalized 0–100 scores per category + overall risk.
    """
    if not DATA_PATH.exists():
        return JSONResponse(status_code=404, content={"error": "No provider data found."})

    try:
        data = json.loads(DATA_PATH.read_text())
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to read applications.json: {e}"})

    record = next(
        (r for r in data if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None
    )

    if not record or "provider" not in record:
        return JSONResponse(status_code=404, content={"error": f"Provider {provider_id} not found."})

    provider = record["provider"]

    # --- Helper for binary or partial compliance ---
    def score_yes_no(value):
        if not value:
            return 100  # Missing data => high risk
        val = str(value).strip().lower()
        if val in ["yes", "true", "valid", "approved"]:
            return 0
        elif val in ["partial", "pending"]:
            return 50
        return 100

    # --- Compute category risks (0 = safe, 100 = high risk) ---
    categories = {}

    # 1️⃣ Compliance (waste, pollution, consent)
    categories["Compliance"] = (
        score_yes_no(provider.get("biomedical_waste_management_authorization")) * 0.4 +
        score_yes_no(provider.get("pollution_control_board_clearance")) * 0.3 +
        score_yes_no(provider.get("consent_to_operate_certificate")) * 0.3
    )

    # 2️⃣ Licensing
    categories["Licensing"] = (
        0 if provider.get("license_number") else 100
    )

    # 3️⃣ Waste
    categories["Waste"] = score_yes_no(provider.get("biomedical_waste_management_authorization"))

    # 4️⃣ Accreditation
    acc = str(provider.get("accreditation_status", "")).lower()
    if "nabh" in acc or "nabl" in acc:
        categories["Accreditation"] = 10
    elif acc in ["none", "na", "not applicable"]:
        categories["Accreditation"] = 80
    else:
        categories["Accreditation"] = 50

    # 5️⃣ Infrastructure
    infra = provider.get("infrastructure_standards_compliance", "")
    categories["Infrastructure"] = 0 if "yes" in str(infra).lower() else 70

    # 6️⃣ Safety
    fire = provider.get("fire_and_lift_inspection_certificates", "")
    categories["Safety"] = 0 if "updated" in str(fire).lower() else 60

    # 7️⃣ Financial (based on ownership)
    owner = str(provider.get("ownership_details", "")).lower()
    if any(word in owner for word in ["govt", "government", "state", "public"]):
        categories["Financial"] = 10
    elif any(word in owner for word in ["trust", "ngo", "foundation"]):
        categories["Financial"] = 30
    else:
        categories["Financial"] = 60

    # --- Weighted average (custom weights per category) ---
    weights = {
        "Compliance": 0.15,
        "Licensing": 0.20,
        "Waste": 0.10,
        "Accreditation": 0.15,
        "Infrastructure": 0.15,
        "Safety": 0.15,
        "Financial": 0.10,
    }

    overall = sum(categories[k] * weights[k] for k in categories)
    risk_level = (
        "Low" if overall < 30 else
        "Moderate" if overall < 60 else
        "High"
    )

    result = {
        "provider_id": provider_id,
        "risk_score": round(overall, 1),
        "level": risk_level,
        "categories": {k: round(v, 1) for k, v in categories.items()}
    }

    return JSONResponse(content=result)
