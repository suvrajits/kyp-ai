# app/services/parser.py
"""
Deterministic parser for fixed-format Provider License PDFs.

Keys are constant across all documents; only values vary.
This parser extracts field values by scanning known label patterns
in text order. It outputs a canonical dictionary compatible
with registry_matcher.py.
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import Dict
from dateutil import parser as dateutil_parser

# ============================================================
# 🧭 Canonical Institutional Keys (matches registry_matcher alias_map)
# ============================================================

CANON_KEYS = [
    "provider_name",
    "license_number",
    "type_of_institution",
    "address",
    "ownership_details",
    "license_issue_date",
    "license_expiry_date",
    "services_offered",
    "number_of_beds_and_wards",
    "number_of_staff",
    "licensing_authority_name",
    "infrastructure_compliance",
    "biomedical_waste_auth",
    "pollution_control_clearance",
    "consent_to_operate",
    "drug_license",
    "radiology_radiation_license",
    "special_act_registration",
    "display_of_charges",
    "compliance_with_standards",
    "support_services",
    "equipment_list",
    "fire_and_lift_certificates",
    "accreditation_status",
    "water_testing_reports",
    "insurance_tieups",
    "quality_protocols",
    "medical_college_affiliation",
    "incident_grievance_mechanism",
]

# ============================================================
# 🧱 Helper Utilities
# ============================================================

COMMON_DATE_FORMATS = [
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
]


def parse_date_to_iso(s: str) -> str:
    """Convert various date formats to ISO (YYYY-MM-DD)."""
    if not s:
        return ""
    s = s.strip().replace("O", "0").replace("o", "0")
    for fmt in COMMON_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    try:
        return dateutil_parser.parse(s, dayfirst=True, fuzzy=True).date().isoformat()
    except Exception:
        return ""


def extract_text_from_pdf(file_path: str) -> str:
    """Simple text extraction using PyMuPDF (fitz)."""
    import fitz

    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text("text") + "\n"
    return text


# ============================================================
# 🧠 Core Parser
# ============================================================

def parse_provider_license(text_or_path: str, debug: bool = False) -> Dict[str, str]:
    """
    Parse fixed-schema provider license document.
    Accepts either raw text or a PDF path.
    Returns dict with canonical keys.
    """

    # Load text
    if text_or_path.lower().endswith(".pdf"):
        text = extract_text_from_pdf(text_or_path)
    else:
        text = text_or_path
    text = re.sub(r"\r", "", text)

    # --- Fixed label list (must match PDF labels) ---
    FIELDS = [
        "Provider Name",
        "License Number",
        "Type of Institution",
        "Address",
        "Ownership Details",
        "License Issue Date",
        "License Expiry Date",
        "Details of Services Offered",
        "Number of Beds and Wards",
        "Qualification and Number of Medical Staff (Doctors, Nurses, Technicians)",
        "Licensing Authority Name",
        "Infrastructure Standards Compliance",
        "Biomedical Waste Management Authorization",
        "Pollution Control Board Clearance",
        "Consent to Operate Certificate",
        "Drug License (if pharmacy services offered)",
        "Radiology-Radiation Safety License (if applicable)",
        "Registration under any Special Acts",
        "Display of Hospital Charges and Facilities",
        "Compliance with Minimum Standards",
        "Details of Support Services",
        "List of Equipment and Medical Devices Used",
        "Fire and Lift Inspection Certificates",
        "Accreditation Status",
        "Water Testing Reports",
        "Insurance Tie-ups and Network Participation",
        "Quality Assurance and Patient Safety Protocols",
        "Affiliation to Medical Colleges",
        "Incident and Grievance Redressal Mechanism Documentation",
    ]

    # --- Extract values between labels deterministically ---
    out: Dict[str, str] = {}
    for i, field in enumerate(FIELDS):
        next_field = FIELDS[i + 1] if i + 1 < len(FIELDS) else None
        # build regex that captures value between this label and the next
        pattern = (
            rf"{re.escape(field)}\s*[:\-]?\s*(.*?)"
            + (rf"(?={re.escape(next_field)})" if next_field else r"$")
        )
        m = re.search(pattern, text, re.S)
        if not m:
            continue
        val = m.group(1).strip().replace("\n", " ").replace("  ", " ")
        val = re.sub(r"(?i)^and\s*wards\s*[:\-]?\s*", "", val)  # fix OCR fragment
        out[field] = val

    # --- Canonical remapping ---
    key_map = {
        "Provider Name": "provider_name",
        "License Number": "license_number",
        "Type of Institution": "type_of_institution",
        "Address": "address",
        "Ownership Details": "ownership_details",
        "License Issue Date": "license_issue_date",
        "License Expiry Date": "license_expiry_date",
        "Details of Services Offered": "services_offered",
        "Number of Beds and Wards": "number_of_beds_and_wards",
        "Qualification and Number of Medical Staff (Doctors, Nurses, Technicians)": "number_of_staff",
        "Licensing Authority Name": "licensing_authority_name",
        "Infrastructure Standards Compliance": "infrastructure_compliance",
        "Biomedical Waste Management Authorization": "biomedical_waste_auth",
        "Pollution Control Board Clearance": "pollution_control_clearance",
        "Consent to Operate Certificate": "consent_to_operate",
        "Drug License (if pharmacy services offered)": "drug_license",
        "Radiology-Radiation Safety License (if applicable)": "radiology_radiation_license",
        "Registration under any Special Acts": "special_act_registration",
        "Display of Hospital Charges and Facilities": "display_of_charges",
        "Compliance with Minimum Standards": "compliance_with_standards",
        "Details of Support Services": "support_services",
        "List of Equipment and Medical Devices Used": "equipment_list",
        "Fire and Lift Inspection Certificates": "fire_and_lift_certificates",
        "Accreditation Status": "accreditation_status",
        "Water Testing Reports": "water_testing_reports",
        "Insurance Tie-ups and Network Participation": "insurance_tieups",
        "Quality Assurance and Patient Safety Protocols": "quality_protocols",
        "Affiliation to Medical Colleges": "medical_college_affiliation",
        "Incident and Grievance Redressal Mechanism Documentation": "incident_grievance_mechanism",
    }

    normalized: Dict[str, str] = {v: out.get(k, "").strip() for k, v in key_map.items()}

    # --- Normalize dates ---
    if normalized.get("license_issue_date"):
        normalized["license_issue_date"] = parse_date_to_iso(normalized["license_issue_date"])
    if normalized.get("license_expiry_date"):
        normalized["license_expiry_date"] = parse_date_to_iso(normalized["license_expiry_date"])

    # --- Normalize boolean-like fields ---
    for k, v in normalized.items():
        val = v.lower().strip()
        if val in {"yes", "true", "available", "displayed", "implemented"}:
            normalized[k] = "Yes"
        elif val in {"no", "false", "not available", "not displayed"}:
            normalized[k] = "No"
        elif val in {"na", "n/a", "not applicable"}:
            normalized[k] = "Not Applicable"

    # --- Filter empties + debug log ---
    normalized = {k: v for k, v in normalized.items() if v}
    if debug:
        missing = [k for k in CANON_KEYS if k not in normalized]
        print(f"🧩 Parsed {len(normalized)} fields, missing {len(missing)}: {missing}")
        for k, v in normalized.items():
            print(f"{k:35}: {v}")

    return normalized


# ============================================================
# 🧪 CLI Test
# ============================================================
if __name__ == "__main__":
    # Example: parse local file or raw text
    sample_pdf = "provider_1.pdf"
    data = parse_provider_license(sample_pdf, debug=True)
    print("\nNormalized Output:\n", data)
