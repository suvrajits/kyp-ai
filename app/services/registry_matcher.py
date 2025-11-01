# app/services/registry_matcher.py

import json
import os
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

# Path to mock registry
REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "..", "mock_data", "providers.json")


# --------------------------------------------------------------------
# 🔧 Key normalization map (aligns JSON fields to canonical keys)
# --------------------------------------------------------------------
KEY_MAP = {
    "Provider Name": "provider_name",
    "License Number": "license_number",
    "Type of Institution": "type_of_institution",
    "Address": "address",
    "Ownership Details": "ownership_details",
    "Licensing Authority Name": "licensing_authority_name",
    "License Issue Date": "license_issue_date",
    "License Expiry Date": "license_expiry_date",
    "Details of Services Offered": "details_of_services_offered",
    "Number of Beds and Wards": "number_of_beds",
    "Qualification and Number of Medical Staff (Doctors, Nurses, Technicians)": "qualification_and_number_of_medical_staff",
    "Infrastructure Standards Compliance": "infrastructure_standards_compliance",
    "Biomedical Waste Management Authorization": "biomedical_waste_management_authorization",
    "Pollution Control Board Clearance": "pollution_control_board_clearance",
    "Consent to Operate Certificate": "consent_to_operate_certificate",
    "Drug License (if pharmacy services offered)": "drug_license",
    "Radiology-Radiation Safety License (if applicable)": "radiology_radiation_safety_license",
    "Registration under any Special Acts": "registration_under_any_special_acts",
    "Display of Hospital Charges and Facilities": "display_of_hospital_charges_and_facilities",
    "Compliance with Minimum Standards": "compliance_with_minimum_standards",
    "Details of Support Services": "details_of_support_services",
    "List of Equipment and Medical Devices Used": "list_of_equipment_and_medical_devices_used",
    "Fire and Lift Inspection Certificates": "fire_and_lift_inspection_certificates",
    "Accreditation Status": "accreditation_status",
}


# --------------------------------------------------------------------
# 📥 Load and normalize provider registry
# --------------------------------------------------------------------
def load_provider_registry() -> List[Dict[str, Any]]:
    """Load and normalize provider registry data from JSON file."""
    if not os.path.exists(REGISTRY_FILE):
        print(f"⚠️ Registry file not found at {REGISTRY_FILE}")
        return []
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        normalized = []
        for entry in raw:
            normalized_entry = {}
            for k, v in entry.items():
                canon_key = KEY_MAP.get(k, k.lower().replace(" ", "_"))
                normalized_entry[canon_key] = v
            normalized.append(normalized_entry)

        return normalized

    except Exception as e:
        print(f"⚠️ Failed to load registry: {e}")
        return []


# --------------------------------------------------------------------
# 🧮 Similarity Computation
# --------------------------------------------------------------------
def compute_similarity(a: str, b: str) -> float:
    """Safely compute case-insensitive similarity between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


# --------------------------------------------------------------------
# 🧠 Match Provider Logic
# --------------------------------------------------------------------
def match_provider(input_fields: Dict[str, str], debug: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Match extracted input_fields against all registry entries.
    Compares all 24 canonical fields and returns per-field similarity + overall match score.
    """
    registry = load_provider_registry()
    if not registry:
        print("⚠️ No registry data available.")
        return None, {"match_percent": 0.0, "per_field": {}, "recommendation": "Registry empty"}

    def safe_str(value):
        """Convert any data type to a cleaned string for comparison."""
        if value is None:
            return ""
        if isinstance(value, (int, float, bool)):
            return str(value).strip()
        return str(value).strip()

    best_match = None
    highest_score = 0.0
    best_field_data = {}

    # Canonical 24 fields
    all_fields = list(KEY_MAP.values())

    # Core weighted identifiers
    weights = {"provider_name": 0.5, "license_number": 0.3, "licensing_authority_name": 0.2}

    for entry in registry:
        field_scores = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for field in all_fields:
            incoming_val = safe_str(input_fields.get(field))
            registry_val = safe_str(entry.get(field))
            sim = compute_similarity(incoming_val, registry_val)
            field_scores[field] = {
                "incoming": incoming_val,
                "registry": registry_val,
                "score": round(sim, 2),
                "method": "string_similarity"
            }

        # Weighted average for confidence
        for field, weight in weights.items():
            weighted_sum += field_scores.get(field, {}).get("score", 0.0) * weight
            total_weight += weight

        avg_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        if avg_score > highest_score:
            highest_score = avg_score
            best_match = entry
            best_field_data = field_scores

    match_result = {
        "match_percent": round(highest_score * 100, 1),
        "per_field": best_field_data,
        "recommendation": (
            "Strong Match" if highest_score >= 0.9
            else "Moderate Match" if highest_score >= 0.75
            else "Low Confidence Match"
        )
    }

    if debug:
        if best_match:
            print(f"✅ Best match: {best_match.get('provider_name', 'Unknown')} ({match_result['match_percent']}%)")
        else:
            print("❌ No matching provider found in registry.")

    return best_match, match_result
