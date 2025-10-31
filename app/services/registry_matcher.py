# app/services/registry_matcher.py
"""
Registry Matcher — compares parsed provider license data against
the official provider registry and computes weighted similarity
scores with expiry penalties and reasoning metadata.
"""

import json, os, re
from difflib import SequenceMatcher
from datetime import datetime, date
from typing import List, Dict, Any, Tuple
from dateutil import parser as date_parser

# ============================================================
# 📁 Registry Path
# ============================================================
REGISTRY_FILE = os.path.join(
    os.path.dirname(__file__), "..", "mock_data", "providers.json"
)

# ============================================================
# ⚖️ Weighted Field Importance (Exact Schema)
# ============================================================
FIELD_WEIGHTS = {
    "Provider Name": 0.20,
    "License Number": 0.20,
    "Licensing Authority Name": 0.09,
    "Ownership Details": 0.10,
    "Address": 0.10,
    "License Issue Date": 0.01,
    "License Expiry Date": 0.10,
    "Type of Institution": 0.01,
    "Details of Services Offered": 0.03,
    "Number of Beds and Wards": 0.01,
    "Qualification and Number of Medical Staff (Doctors, Nurses, Technicians)": 0.03,
    "Accreditation Status": 0.02,
    "Infrastructure Standards Compliance": 0.02,
    "Biomedical Waste Management Authorization": 0.02,
    "Pollution Control Board Clearance": 0.01,
    "Consent to Operate Certificate": 0.02,
    "Drug License (if pharmacy services offered)": 0.02,
    "Radiology-Radiation Safety License (if applicable)": 0.02,
}

# Normalize weights
TOTAL_WEIGHT = sum(FIELD_WEIGHTS.values())
for k in FIELD_WEIGHTS:
    FIELD_WEIGHTS[k] /= TOTAL_WEIGHT

THRESHOLDS = {"accept": 0.95, "verify": 0.70, "review": 0.50}
EXPIRY_PENALTY_PERCENT = 15

# ============================================================
# 🧩 Helpers
# ============================================================

def coerce_to_str(val: Any) -> str:
    """Safely coerce any data type to a normalized string."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False)
        except Exception:
            return str(val)
    return str(val)


def normalize_text(s: Any) -> str:
    """Normalize any data type safely for consistent comparison."""
    s = coerce_to_str(s).lower().strip()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    synonyms = {
        "yes": "true",
        "no": "false",
        "not applicable": "na",
        "pending": "pending",
        "available": "true",
        "displayed": "true",
        "not displayed": "false",
        "implemented": "true",
        "in progress": "progress",
    }
    return synonyms.get(s, s)


def compute_similarity(a: Any, b: Any) -> float:
    """Compute a safe similarity score between any two values."""
    a, b = coerce_to_str(a), coerce_to_str(b)
    if not a.strip() or not b.strip():
        return 0.0
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def parse_date_to_iso(s: Any) -> str:
    """Try to normalize any date string to ISO YYYY-MM-DD."""
    s = coerce_to_str(s)
    if not s:
        return ""
    try:
        dt = date_parser.parse(s, dayfirst=True, fuzzy=True)
        return dt.date().isoformat()
    except Exception:
        return ""


def is_expired(date_str: Any) -> bool:
    """True if expiry date has passed today."""
    s = parse_date_to_iso(date_str)
    if not s:
        return False
    try:
        expiry = datetime.fromisoformat(s).date()
        return expiry < date.today()
    except Exception:
        return False


def score_field(a: Any, b: Any, field_name: str = "") -> Tuple[float, str]:
    """Compute field similarity score and reasoning method."""
    a, b = coerce_to_str(a), coerce_to_str(b)
    if not a or not b:
        return 0.0, "missing"

    # --- Expiry Date Handling ---
    if "expiry date" in field_name.lower():
        a_iso, b_iso = parse_date_to_iso(a), parse_date_to_iso(b)
        if not a_iso or not b_iso:
            return 0.0, "invalid_date"
        if a_iso == b_iso:
            return (0.0, "expired") if is_expired(a_iso) else (1.0, "exact")
        return (0.5, "mismatch_date")

    # --- Issue Date Handling ---
    if "issue date" in field_name.lower():
        a_iso, b_iso = parse_date_to_iso(a), parse_date_to_iso(b)
        if not a_iso or not b_iso:
            return 0.0, "invalid_date"
        return (1.0, "exact") if a_iso == b_iso else (0.5, "mismatch_date")

    # --- Boolean Handling ---
    a_norm, b_norm = normalize_text(a), normalize_text(b)
    if a_norm in {"true", "false"} and b_norm in {"true", "false"}:
        return (1.0, "boolean_match") if a_norm == b_norm else (0.0, "boolean_mismatch")

    # --- General Text Similarity ---
    if a_norm == b_norm:
        return 1.0, "exact"
    ratio = compute_similarity(a_norm, b_norm)
    if ratio >= 0.95:
        return ratio, "exact"
    elif ratio >= 0.85:
        return ratio, "near"
    elif ratio >= 0.6:
        return ratio, "weak"
    else:
        return 0.0, "mismatch"


def load_provider_registry() -> List[Dict[str, Any]]:
    """Load provider registry JSON file and flatten nested structures."""
    if not os.path.exists(REGISTRY_FILE):
        print(f"⚠️ Missing registry file: {REGISTRY_FILE}")
        return []

    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                print("⚠️ Registry root is not a list.")
                return []
            # Flatten nested dicts/lists early
            for entry in data:
                for k, v in list(entry.items()):
                    if isinstance(v, (dict, list)):
                        entry[k] = coerce_to_str(v)
            return data
    except Exception as e:
        print(f"⚠️ Failed to load registry: {e}")
        return []


# ============================================================
# 🧠 Core Matching Logic
# ============================================================

def sanitize_incoming_value(val: Any) -> str:
    """Clean meaningless placeholder values."""
    val = coerce_to_str(val).strip()
    val_lower = val.lower()
    invalids = {"", "/", "-", "—", "na", "n/a", "none", "nil"}
    return "" if val_lower in invalids else val


def match_provider(input_fields: Dict[str, Any], debug: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compare parsed provider data against registry entries."""
    alias_map = {
        "provider_name": "Provider Name",
        "license_number": "License Number",
        "license_issue_date": "License Issue Date",
        "license_expiry_date": "License Expiry Date",
        "type_of_institution": "Type of Institution",
        "ownership_details": "Ownership Details",
        "address": "Address",
        "licensing_authority_name": "Licensing Authority Name",
        "services_offered": "Details of Services Offered",
        "number_of_beds_and_wards": "Number of Beds and Wards",
        "number_of_staff": "Qualification and Number of Medical Staff (Doctors, Nurses, Technicians)",
        "infrastructure_compliance": "Infrastructure Standards Compliance",
        "biomedical_waste_auth": "Biomedical Waste Management Authorization",
        "pollution_control_clearance": "Pollution Control Board Clearance",
        "consent_to_operate": "Consent to Operate Certificate",
        "drug_license": "Drug License (if pharmacy services offered)",
        "radiology_radiation_license": "Radiology-Radiation Safety License (if applicable)",
        "accreditation_status": "Accreditation Status",
        "special_act_registration": "Registration under any Special Acts",
        "display_of_charges": "Display of Hospital Charges and Facilities",
        "compliance_with_standards": "Compliance with Minimum Standards",
        "support_services": "Details of Support Services",
        "equipment_list": "List of Equipment and Medical Devices Used",
        "fire_and_lift_certificates": "Fire and Lift Inspection Certificates",
        "water_testing_reports": "Water Testing Reports",
        "insurance_tieups": "Insurance Tie-ups and Network Participation",
        "quality_protocols": "Quality Assurance and Patient Safety Protocols",
        "medical_college_affiliation": "Affiliation to Medical Colleges",
        "incident_grievance_mechanism": "Incident and Grievance Redressal Mechanism Documentation",
    }

    input_fields = {alias_map.get(k, k): v for k, v in input_fields.items()}

    def _get_val(field: str, source: Dict[str, Any]):
        if field in source:
            return source[field]
        key = (
            field.lower()
            .replace("(", "")
            .replace(")", "")
            .replace("/", "")
            .replace(" ", "_")
            .replace("-", "_")
        )
        return source.get(key)

    registry = load_provider_registry()
    if not registry:
        return None, {
            "match_percent": 0.0,
            "recommendation": "🔴 No Match",
            "reason": "Registry missing or empty.",
            "per_field": {},
            "timestamp": datetime.utcnow().isoformat(),
        }

    best_match, best_score, best_result = None, 0.0, {}
    for entry in registry:
        per_field, total_score, active_weight = {}, 0.0, 0.0

        for field, weight in FIELD_WEIGHTS.items():
            val_a = sanitize_incoming_value(_get_val(field, input_fields))
            val_b = sanitize_incoming_value(entry.get(field, ""))
            score, method = score_field(val_a, val_b, field)
            per_field[field] = {
                "incoming": val_a,
                "registry": val_b,
                "score": round(score, 3),
                "method": method,
                "weight": weight,
            }
            total_score += score * weight
            if score > 0:
                active_weight += weight

        match_score = (total_score / active_weight) if active_weight else 0.0
        if active_weight < 0.4:
            match_score *= 0.8

        expiry_field = "License Expiry Date"
        expiry_val = per_field.get(expiry_field, {}).get("registry") or per_field.get(expiry_field, {}).get("incoming")
        expired = is_expired(expiry_val)
        if expired:
            match_score = max(0.0, match_score - (EXPIRY_PENALTY_PERCENT / 100))
            if expiry_field in per_field:
                per_field[expiry_field]["method"] = "expired"
                per_field[expiry_field]["score"] = 0.0

        if match_score > best_score:
            best_score = match_score
            best_match = entry
            best_result = {
                "match_percent": round(match_score * 100, 2),
                "per_field": per_field,
                "expired": expired,
                "expiry_penalty_applied": expired,
                "timestamp": datetime.utcnow().isoformat(),
            }

    if best_score >= THRESHOLDS["accept"]:
        rec, reason = "✅ Auto-Accept", "High-confidence match across key institutional identifiers."
    elif best_score >= THRESHOLDS["verify"]:
        rec, reason = "🟡 Accept (Verify)", "Moderate match; core identifiers align but some compliance fields differ."
    elif best_score >= THRESHOLDS["review"]:
        rec, reason = "🟠 Manual Review", "Low match confidence; verify key details like license or ownership."
    else:
        rec, reason = "🔴 No Match", "Fields did not align beyond weak similarity thresholds."

    best_result["recommendation"] = rec
    best_result["reason"] = reason

    if debug:
        print(f"\n🏥 Best match: {best_match.get('Provider Name', 'Unknown')} — {best_score*100:.1f}% ({rec})")
        for f, data in best_result["per_field"].items():
            if data["score"] < 1.0:
                print(f"⚠ {f}: '{data['incoming']}' vs '{data['registry']}' → {data['score']} ({data['method']})")

    return best_match, best_result


# ============================================================
# 🧪 CLI Test
# ============================================================
if __name__ == "__main__":
    test_input = {
        "provider_name": "Saraswati Kolkata Hospital",
        "license_number": "WB/MC/2023/01002",
        "license_issue_date": "08-04-2020",
        "license_expiry_date": "08-04-2025",
        "licensing_authority_name": "District Health Authority",
    }

    match, result = match_provider(test_input, debug=True)
    print(json.dumps(result, indent=2))
