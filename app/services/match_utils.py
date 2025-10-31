import re
import unicodedata
from rapidfuzz import fuzz

def normalize_text(s: str) -> str:
    if not s: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = s.lower().strip()
    s = re.sub(r'[\.,/\\\-():]', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    # optional: expand common abbreviations map if needed
    return s

def normalize_license(lic: str) -> str:
    if not lic: return ""
    s = normalize_text(lic)
    # remove spaces and common separators for robust compare
    return re.sub(r'[^a-z0-9]', '', s)

def token_set_score(a: str, b: str) -> int:
    return fuzz.token_set_ratio(a or "", b or "")

def partial_ratio(a: str, b: str) -> int:
    return fuzz.partial_ratio(a or "", b or "")
