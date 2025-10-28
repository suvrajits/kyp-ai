# app/services/parser.py
from __future__ import annotations
import re
from typing import Dict, Any

# ---------- canonical keys we want ----------
CANON_KEYS = [
    "provider_name", "license_number", "specialty", "state",
    "issuing_authority", "issue_date", "expiry_date", "registration_id"
]

# ---------- label synonyms → canonical ----------
_SYNONYM_MAP = {
    "provider_name": {
        "providername", "name", "doctorname", "drname",
        "practitioner", "practitionername", "doctor", "doctor name"
    },
    "license_number": {
        "licensenumber", "licencenumber", "licenceno", "licenseno",
        "registrationno", "registrationnumber", "regno", "regnno",
        "regnnumber", "licence", "license"
    },
    "specialty": {"specialty", "speciality", "department", "field", "practicearea"},
    "issuing_authority": {"issuingauthority", "authority", "council", "board",
                          "medicalcouncil", "statecouncil", "verificationbody"},
    "issue_date": {"issuedate", "dateofissue", "dateissued"},
    "expiry_date": {"expirydate", "expirationdate", "validtill", "validupto", "validuntil"},
    "registration_id": {"registrationid", "regid", "registration", "certificateid", "certid"},
    "state": {"state", "state/ut", "province", "jurisdiction", "registeredjurisdiction"},
}

# ---------- common Indian license prefixes → state inference ----------
_PREFIX_TO_STATE = {
    "MH": "Maharashtra", "DL": "Delhi", "GJ": "Gujarat", "KA": "Karnataka",
    "TN": "Tamil Nadu", "WB": "West Bengal", "RJ": "Rajasthan", "UP": "Uttar Pradesh",
    "PB": "Punjab", "HR": "Haryana", "BR": "Bihar", "MP": "Madhya Pradesh",
    "KL": "Kerala", "TS": "Telangana", "AP": "Andhra Pradesh",
    "UK": "Uttarakhand", "UA": "Uttarakhand", "CG": "Chhattisgarh",
    "OR": "Odisha", "OD": "Odisha", "JK": "Jammu & Kashmir", "JH": "Jharkhand",
    "AS": "Assam"
}

# ---------- Indian states for authority-based detection ----------
_STATES = {v.lower() for v in _PREFIX_TO_STATE.values()} | {
    "andaman and nicobar", "arunachal pradesh", "goa", "himachal pradesh",
    "meghalaya", "manipur", "mizoram", "nagaland", "sikkim", "tripura",
    "ladakh", "lakshadweep", "puducherry", "chandigarh",
    "dadra and nagar haveli", "daman and diu"
}

# ============================================================
# 🔧 Helper Utilities
# ============================================================

def _norm(s: str) -> str:
    """Normalize label text for matching."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def _map_label_to_canon(label: str) -> str | None:
    """Map a raw OCR label to a canonical key."""
    n = _norm(label)
    for canon, synonyms in _SYNONYM_MAP.items():
        if n in synonyms:
            return canon
    return None

def _flatten_extraction(extracted: Any) -> str:
    """
    Turn DI output into a line-wise text blob:
    - include "Key: Value" from key_value_pairs
    - include raw paragraphs
    """
    if isinstance(extracted, str):
        return extracted

    lines = []
    if isinstance(extracted, dict):
        for kv in (extracted.get("key_value_pairs") or []):
            k = (kv.get("key") or "").strip()
            v = (kv.get("value") or "").strip()
            if k or v:
                lines.append(f"{k}: {v}")
        for p in (extracted.get("paragraphs") or []):
            if p:
                lines.append(p.strip())

    blob = "\n".join(lines)
    blob = re.sub(r"[ \t]+", " ", blob)  # keep newlines for ^ anchors
    return blob

def _strip_leading_punct(val: str) -> str:
    """Removes leading ':', '-', '.', etc."""
    return re.sub(r"^[\s:\-–•.]+", "", (val or "").strip())

def _cut_at_next_label(val: str) -> str:
    """Cuts off trailing glued labels like 'NephrologyExpiryDate:...' etc."""
    return re.split(
        r"(?i)\b("
        r"provider|practitioner|specialit?y|field\s*of\s*practice|licen[cs]e|registration|"
        r"issuing|issue|expiry|valid\s*till|state|council|authority"
        r")\b", val
    )[0].strip()

def _clean(val: str) -> str:
    """Standard cleanup pipeline for parsed values."""
    val = _strip_leading_punct(val)
    val = re.sub(r"\s{2,}", " ", val)
    val = _cut_at_next_label(val)
    val = re.sub(r"(?i)\s+specialt?y$", "", val).strip()
    val = re.sub(r"(?i)\bof\s+practice\b", "", val).strip()
    return val

def _infer_state(value_dict: Dict[str, str]) -> str:
    """Infer state based on authority text or license prefix."""
    # 1) From issuing authority text
    auth = (value_dict.get("issuing_authority") or "").lower()
    for st in _STATES:
        if st in auth:
            return st.title()

    # 2) From license prefix
    lic = (value_dict.get("license_number") or "").strip()
    m = re.match(r"([A-Z]{2})", lic)
    if m:
        return _PREFIX_TO_STATE.get(m.group(1), "")

    return ""

# ============================================================
# 🧠 Main Parsing Logic
# ============================================================

def parse_provider_license(extracted: Any) -> Dict[str, str]:
    """
    Robustly parse provider fields from DI output (paragraphs + KV pairs)
    with fuzzy label mapping, regex fallback, and smart contextual heuristics.
    """
    out: Dict[str, str] = {k: "" for k in CANON_KEYS}

    # ---- 1) Use key_value_pairs with fuzzy label mapping ----
    if isinstance(extracted, dict):
        for kv in (extracted.get("key_value_pairs") or []):
            canon = _map_label_to_canon(kv.get("key", ""))
            if not canon:
                continue
            val = _clean(kv.get("value", ""))
            if val and not out.get(canon):
                out[canon] = val

    # ---- 2) Fallback via regex on flattened text ----
    text = _flatten_extraction(extracted)

    patterns = {
        "provider_name": (
            r"(?im)^\s*(?:provider\s*name|practitioner\s*name|doctor\s*name|name)\s*[:\-]?\s*(.+)$"
        ),
        "license_number": (
            r"(?im)^\s*(?:licen[cs]e\s*(?:no\.?|number)|registration\s*(?:no\.?|number))\s*[:\-]?\s*([A-Z0-9\-\/]+)"
        ),
        "specialty": (
            r"(?im)^\s*(?:"  # field variations
            r"field\s*of\s*practice|"
            r"area\s*of\s*practice|"
            r"practice\s*area|"
            r"medical\s*specialit?y|"
            r"specialit?y|"
            r"department|"
            r"field"
            r")\s*[:\-]?\s*(.+)$"
        ),
        "issuing_authority": (
            r"(?im)^\s*(?:issuing\s*authorit(?:y|ies)|authority|council|board|verification\s*body)\s*[:\-]?\s*(.+)$"
        ),
        "issue_date": (
            r"(?im)^\s*(?:issue\s*date|date\s*of\s*issue|date\s*issued)\s*[:\-]?\s*(.+)$"
        ),
        "expiry_date": (
            r"(?im)^\s*(?:expir(?:y|ation)\s*date|valid\s*(?:till|upto|until))\s*[:\-]?\s*(.+)$"
        ),
        "registration_id": (
            r"(?im)^\s*(?:registration(?:\s*(?:id|number))?|cert(?:ificate)?\s*id)\s*[:\-]?\s*([A-Z0-9\-\/]+)"
        ),
        "state": (
            r"(?im)^\s*(?:state|state/ut|province|jurisdiction|registered\s*jurisdiction)\s*[:\-]?\s*(.+)$"
        ),
    }

    for k, pat in patterns.items():
        if out.get(k):
            continue
        m = re.search(pat, text)
        if m:
            out[k] = _clean(m.group(1))

    # ---- 2.5) Secondary fallback: detect "Dr. <Name>" if still empty ----
    if not out.get("provider_name"):
        m = re.search(r"(?i)\bdr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", text)
        if m:
            out["provider_name"] = _clean(m.group(0))

    # ---- 2.6) Context fallback: line above "Reg. No" / "License" ----
    if not out.get("provider_name"):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if re.search(r"(?i)(licen[cs]e|reg\.?\s*no|registration)", line):
                if i > 0 and not re.search(r"(?i)(license|reg|council|authority)", lines[i - 1]):
                    candidate = lines[i - 1]
                    if len(candidate.split()) <= 6 and re.search(r"[A-Z][a-z]+", candidate):
                        out["provider_name"] = _clean(candidate)
                        break

    # ---- 3) Cleanup pass ----
    for k in out:
        out[k] = _strip_leading_punct(out[k])

    # ---- 4) Infer state if missing ----
    if not out.get("state"):
        out["state"] = _infer_state(out)

    return out
