# app/services/application_store.py
import json, os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from app.services.id_utils import generate_temp_id  # ✅ isolated utility (no circular import)
from threading import Lock

# ============================================================
# ⚙️ Path setup
# ============================================================
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "applications.json"
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

# Thread-safe file operations
_LOCK = Lock()

# ============================================================
# 🧩 Internal Utilities
# ============================================================

def _now_iso() -> str:
    """Returns current UTC timestamp."""
    return datetime.utcnow().isoformat()


def _normalize_id(rec: Dict) -> str:
    """
    Ensure each record has both `id` and `application_id`.
    Returns the canonical ID used across the app.
    """
    if not isinstance(rec, dict):
        return ""
    app_id = rec.get("id")
    alt_id = rec.get("application_id")

    if not app_id and alt_id:
        rec["id"] = alt_id
    elif not alt_id and app_id:
        rec["application_id"] = app_id
    elif not app_id and not alt_id:
        temp = generate_temp_id()
        rec["id"] = temp
        rec["application_id"] = temp

    return rec["id"]


def _ensure_defaults(rec: Dict) -> None:
    """Assign safe defaults to missing fields."""
    rec.setdefault("status", "Under Review")
    rec.setdefault("provider", {})
    rec.setdefault("documents", [])
    rec.setdefault("created_at", _now_iso())
    rec.setdefault("messages", [])
    rec.setdefault("history", [])


def _atomic_write(path: Path, data: List[Dict]):
    """Perform atomic file write with a temporary backup."""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


# ============================================================
# 📘 Load / Save
# ============================================================

def load_applications() -> List[Dict]:
    """Read and normalize application records from disk."""
    if not DATA_PATH.exists():
        print("📄 No applications.json found — initializing empty dataset.")
        return []

    try:
        with _LOCK:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Corrupted JSON detected in {DATA_PATH}, resetting file.")
        _atomic_write(DATA_PATH, [])
        return []
    except Exception as e:
        print(f"⚠️ Error reading {DATA_PATH}: {e}")
        return []

    normalized = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        _normalize_id(rec)
        _ensure_defaults(rec)
        _auto_clean_old_versions(rec)
        normalized.append(rec)

    # Auto-heal invalid records on load
    try:
        _atomic_write(DATA_PATH, normalized)
    except Exception as e:
        print(f"⚠️ Failed to rewrite normalized applications: {e}")

    print(f"📂 Loaded {len(normalized)} application(s).")
    return normalized


def save_all(apps: List[Dict]):
    """Safely overwrite all applications with normalization."""
    try:
        for rec in apps:
            _normalize_id(rec)
            _ensure_defaults(rec)

        with _LOCK:
            _atomic_write(DATA_PATH, apps)

        print(f"✅ Saved {len(apps)} application(s) → {DATA_PATH}")
    except Exception as e:
        print(f"❌ Error saving applications: {e}")


# ============================================================
# 🧩 Upsert Logic (Create / Update)
# ============================================================

def upsert_application(record: Dict, key_fields=("provider_name", "license_number")) -> str:
    """
    Create or update a provider record based on name + license_number.
    Now extended to merge license matching results (match_result, match_explanation, match_recommendation, etc.).
    Returns the canonical ID (TEMP-ID or APP-ID).
    Maintains history, preserves explicit status.
    """
    apps = load_applications()
    provider = record.get("provider", {}) or {}

    name = (provider.get("provider_name") or "").strip().lower()
    lic = (provider.get("license_number") or "").strip().lower()

    found_idx = -1
    for i, app in enumerate(apps):
        prov = app.get("provider", {}) or {}
        if (
            prov.get("provider_name", "").strip().lower() == name
            and prov.get("license_number", "").strip().lower() == lic
        ):
            found_idx = i
            break

    # 🔁 Update existing
    if found_idx >= 0:
        existing = apps[found_idx]

        # --- Smart merge: preserve nested match_result and history ---
        if "match_result" in record and "match_result" in existing:
            merged_match = {**existing["match_result"], **record["match_result"]}
            existing["match_result"] = merged_match
        elif "match_result" in record:
            existing["match_result"] = record["match_result"]

        # Update other new fields
        for k in ["match_explanation", "match_recommendation", "match_percent"]:
            if k in record:
                existing[k] = record[k]

        # Shallow merge rest
        existing.update({k: v for k, v in record.items() if k not in ("match_result",)})

        _normalize_id(existing)
        if "status" not in record:
            existing["status"] = existing.get("status", "Under Review")

        existing.setdefault("history", []).append({
            "event": f"Updated ({existing['status']})",
            "timestamp": _now_iso(),
        })
        apps[found_idx] = existing
        print(f"🔁 Updated existing record for {name or lic}")

    # 🆕 New record
    else:
        temp_id = record.get("id") or record.get("application_id")
        if not temp_id:
            temp_id = generate_temp_id()

        record["id"] = temp_id
        record["application_id"] = temp_id
        _normalize_id(record)
        _ensure_defaults(record)

        # Ensure match fields exist even if missing
        record.setdefault("match_result", {"match_percent": 0.0, "recommendation": "Not Matched", "per_field": {}})
        record.setdefault("match_explanation", {})
        record.setdefault("match_recommendation", "Not Matched")
        record.setdefault("match_percent", 0.0)

        record.setdefault("history", []).append({
            "event": "Created",
            "timestamp": _now_iso(),
        })
        apps.append(record)
        print(f"🆕 Added new record for {name or lic} with ID {temp_id}")

    save_all(apps)
    rec = record if found_idx < 0 else apps[found_idx]
    return rec.get("id", rec.get("application_id", ""))



# ============================================================
# 🔍 Utility Finders
# ============================================================

def find_application(app_id: str) -> Optional[Dict]:
    """Retrieve a single record by ID or application_id."""
    apps = load_applications()
    for rec in apps:
        if rec.get("id") == app_id or rec.get("application_id") == app_id:
            return rec
    return None


def append_message(app_id: str, sender: str, text: str):
    """Append a message and history entry to a record."""
    apps = load_applications()
    for rec in apps:
        if rec.get("id") == app_id or rec.get("application_id") == app_id:
            msg = {"from": sender, "text": text, "timestamp": _now_iso()}
            rec.setdefault("messages", []).append(msg)
            rec.setdefault("history", []).append({
                "event": f"Message from {sender}",
                "timestamp": _now_iso(),
            })
            save_all(apps)
            print(f"💬 Added message to {app_id} by {sender}")
            return
    print(f"⚠️ No record found for message append: {app_id}")


# ============================================================
# 🔄 Lifecycle Helpers
# ============================================================

def update_status(app_id: str, new_status: str, note: str = "") -> bool:
    """Update the status of an application (Approve / Reject / Info Request)."""
    apps = load_applications()
    updated = False
    for rec in apps:
        if rec.get("id") == app_id or rec.get("application_id") == app_id:
            old_status = rec.get("status", "Unknown")
            rec["status"] = new_status
            rec.setdefault("history", []).append({
                "event": f"Status changed from {old_status} → {new_status}",
                "timestamp": _now_iso(),
                "note": note,
            })
            updated = True
            break
    if updated:
        save_all(apps)
        print(f"🔄 Status for {app_id} → {new_status}")
    else:
        print(f"⚠️ Could not find record {app_id} to update status.")
    return updated


def list_applications_by_status(status_filter: Optional[str] = None) -> List[Dict]:
    """Return all applications filtered by status (if given)."""
    apps = load_applications()
    if status_filter:
        return [a for a in apps if a.get("status", "").lower() == status_filter.lower()]
    return apps

def append_application(record: Dict):
    """Alias for upsert_application for backward compatibility."""
    return upsert_application(record)

def _auto_clean_old_versions(rec: Dict) -> None:
    """
    Upgrade older application records to the latest schema version.
    Adds missing keys like match_result, risk_scores, watchlist_hits, etc.
    Ensures backward compatibility and prepares for risk profiling.
    """
    # --- Core defaults ---
    rec.setdefault("provider", {})
    rec.setdefault("documents", [])
    rec.setdefault("messages", [])
    rec.setdefault("history", [])
    rec.setdefault("status", "Under Review")

    # --- Matching fields ---
    if "match_result" not in rec or not isinstance(rec["match_result"], dict):
        rec["match_result"] = {
            "match_percent": rec.get("match_percent", 0.0),
            "recommendation": rec.get("match_recommendation", "Not Matched"),
            "per_field": {}
        }

    rec.setdefault("match_percent", rec["match_result"].get("match_percent", 0.0))
    rec.setdefault("match_recommendation", rec["match_result"].get("recommendation", "Not Matched"))
    rec.setdefault("match_explanation", {})

    # --- Risk scoring placeholders ---
    default_risk_scores = {
        "cybersecurity": 0.0,
        "data_privacy": 0.0,
        "operational": 0.0,
        "financial": 0.0,
        "regulatory": 0.0,
        "reputational": 0.0,
        "supply_chain": 0.0
    }
    rec.setdefault("risk_scores", default_risk_scores)

    # --- Watchlist and compliance placeholders ---
    rec.setdefault("watchlist_hits", [])        # list of {category, description, severity}
    rec.setdefault("compliance_flags", [])      # list of {rule, severity, note}

    # --- AI explanation ---
    rec.setdefault("ai_explanation", "")        # human-readable reasoning from the AI

    # --- Basic created_at ---
    rec.setdefault("created_at", datetime.utcnow().isoformat())

    # --- Normalize IDs ---
    _normalize_id(rec)
