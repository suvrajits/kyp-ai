# app/services/parser.py
"""
Azure Document Intelligence–based Provider License Parser.

This version directly invokes Azure Document Intelligence using the custom
trained model stored in your Key Vault at:
    https://providergpt-kv.vault.azure.net/

It extracts key-value fields and maps them into the canonical schema.
"""

import os
import logging
from datetime import datetime
from typing import Dict
from dateutil import parser as dateutil_parser
from app.services.azure_docai_extractor import AzureDocumentExtractor

# -------------------------------------------------------
# 📍 Fixed Vault URL (no .env dependency)
# -------------------------------------------------------
VAULT_URL = "https://providergpt-kv.vault.azure.net/"

# -------------------------------------------------------
# 🧭 Canonical Provider License Fields
# -------------------------------------------------------
CANON_KEYS = [
    "provider_name",
    "license_number",
    "type_of_institution",
    "address",
    "ownership_details",
    "license_issue_date",
    "license_expiry_date",
    "details_of_services_offered",
    "number_of_beds",
    "qualification_and_number_of_medical_staff",
    "licensing_authority_name",
    "infrastructure_standards_compliance",
    "biomedical_waste_management_authorization",
    "pollution_control_board_clearance",
    "consent_to_operate_certificate",
    "drug_license",
    "radiology_radiation_safety_license",
    "registration_under_any_special_acts",
    "display_of_hospital_charges_and_facilities",
    "compliance_with_minimum_standards",
    "details_of_support_services",
    "list_of_equipment_and_medical_devices_used",
    "fire_and_lift_inspection_certificates",
    "accreditation_status",
]

# -------------------------------------------------------
# 🧮 Helper: Date Normalization
# -------------------------------------------------------
COMMON_DATE_FORMATS = [
    "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y"
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


# -------------------------------------------------------
# 🧠 Main Parser Function
# -------------------------------------------------------
def parse_provider_license(pdf_path: str, debug: bool = False) -> Dict[str, str]:
    """
    Parse a provider license PDF using Azure Document Intelligence.
    Extracts and normalizes canonical fields.
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"❌ File not found: {pdf_path}")

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    logger.info(f"📄 Parsing provider license using Azure Document Intelligence (Vault: {VAULT_URL})")

    # Initialize Azure Document Extractor (using fixed Vault URL)
    extractor = AzureDocumentExtractor(vault_url=VAULT_URL)
    result = extractor.extract_from_pdf(pdf_path)

    if not result:
        raise ValueError("⚠️ No fields were extracted from the document.")

    # ---------------------------------------------------
    # 🔖 Azure → Canonical Key Mapping
    # ---------------------------------------------------
    key_map = {
        "Provider Name": "provider_name",
        "License Number": "license_number",
        "Type of Institution": "type_of_institution",
        "Address": "address",
        "Ownership Details": "ownership_details",
        "License Issue Date": "license_issue_date",
        "License Expiry Date": "license_expiry_date",
        "Details of Services Offered": "details_of_services_offered",
        "Number of Beds": "number_of_beds",
        "Qualification and Number of Medical Staff": "qualification_and_number_of_medical_staff",
        "Licensing Authority Name": "licensing_authority_name",
        "Infrastructure Standards Compliance": "infrastructure_standards_compliance",
        "Biomedical Waste Management Authorization": "biomedical_waste_management_authorization",
        "Pollution Control Board Clearance": "pollution_control_board_clearance",
        "Consent to Operate Certificate": "consent_to_operate_certificate",
        "Drug License": "drug_license",
        "Radiology-Radiation Safety License": "radiology_radiation_safety_license",
        "Registration under any Special Acts": "registration_under_any_special_acts",
        "Display of Hospital Charges and Facilities": "display_of_hospital_charges_and_facilities",
        "Compliance with Minimum Standards": "compliance_with_minimum_standards",
        "Details of Support Services": "details_of_support_services",
        "List of Equipment and Medical Devices Used": "list_of_equipment_and_medical_devices_used",
        "Fire and Lift Inspection Certificates": "fire_and_lift_inspection_certificates",
        "Accreditation Status": "accreditation_status",
    }

    # ---------------------------------------------------
    # 🧹 Normalize and Clean Results
    # ---------------------------------------------------
    normalized: Dict[str, str] = {}

    for azure_key, canon_key in key_map.items():
        val = result.get(azure_key, "") or result.get(canon_key, "")
        if isinstance(val, str):
            normalized[canon_key] = val.strip()
        elif val is not None:
            normalized[canon_key] = str(val).strip()

    # Convert date fields
    for key in ("license_issue_date", "license_expiry_date"):
        if normalized.get(key):
            normalized[key] = parse_date_to_iso(normalized[key])

    # Boolean-like normalization
    for k, v in list(normalized.items()):
        val = v.lower().strip()
        if val in {"yes", "true", "available", "displayed", "implemented"}:
            normalized[k] = "Yes"
        elif val in {"no", "false", "not available", "not displayed"}:
            normalized[k] = "No"
        elif val in {"na", "n/a", "not applicable"}:
            normalized[k] = "Not Applicable"

    # Remove empties
    normalized = {k: v for k, v in normalized.items() if v}

    if debug:
        print(f"🧩 Extracted {len(normalized)} fields:")
        for k, v in normalized.items():
            print(f"{k:45}: {v}")

    logger.info(f"✅ Extraction complete ({len(normalized)} fields).")
    return normalized


# -------------------------------------------------------
# 🧪 CLI Test
# -------------------------------------------------------
if __name__ == "__main__":
    PDF_PATH = r"C:\Users\suvra\OneDrive\Desktop\Resume\Portfolio\Healthcare\New_provider_pdfs\provider_59.pdf"
    data = parse_provider_license(PDF_PATH, debug=True)
    print("\nNormalized Output:\n", data)
