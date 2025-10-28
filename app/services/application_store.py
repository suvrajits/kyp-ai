# app/services/application_store.py
import json, os
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from app.routes.upload import generate_temp_id  # ✅ reuse existing ID generator

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "applications.json"
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 📘 Load / Save Helpers
# ============================================================
def load_applications() -> List[Dict]:
    """Reliable loader that always reads fresh from disk, 
    normalizing legacy records for backward compatibility."""
    if not DATA_PATH.exists():
        print("📄 No existing applications file found — starting fresh.")
        return []

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"📂 Loaded {len(data)} existing applications from disk.")

            normalized = []
            for rec in data:
                # Defensive dictionary handling
                if not isinstance(rec, dict):
                    continue

                # Ensure ID consistency between `id` and `application_id`
                app_id = rec.get("id")
                alt_id = rec.get("application_id")

                if not app_id and alt_id:
                    rec["id"] = alt_id
                elif not alt_id and app_id:
                    rec["application_id"] = app_id
                elif not app_id and not alt_id:
                    # assign a generic placeholder ID for unidentified records
                    rec["id"] = f"TEMP-ID-UNASSIGNED-{len(normalized)+1}"
                    rec["application_id"] = rec["id"]

                # Ensure status field is valid
                if not rec.get("status"):
                    rec["status"] = "Under Review"

                # Ensure required sections exist
                rec.setdefault("provider", {})
                rec.setdefault("documents", [])
                rec.setdefault("created_at", datetime.utcnow().isoformat())

                normalized.append(rec)

            # If normalization modified records, re-save them
            if normalized != data:
                with open(DATA_PATH, "w", encoding="utf-8") as wf:
                    json.dump(normalized, wf, indent=2)
                print(f"✅ Normalized and resaved {len(normalized)} records.")

            return normalized

    except Exception as e:
        print(f"⚠️ Error reading or parsing {DATA_PATH}: {e}")
        return []



def save_all(apps: List[Dict]):
    """Safely overwrite all application records."""
    try:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(apps, f, indent=2)
        print(f"✅ Successfully saved {len(apps)} applications.")
        print(f"💾 File path: {DATA_PATH}")
    except Exception as e:
        print(f"❌ Error writing {DATA_PATH}: {e}")


# ============================================================
# 🧩 Upsert Logic
# ============================================================
def upsert_application(record: Dict, key_fields=("provider_name", "license_number")) -> str:
    """
    Insert or update a provider record based on name/license_number.
    Ensures both `id` and `application_id` fields exist for grid compatibility.
    Always defaults to 'Under Review' for new entries.
    Returns the assigned TEMP-ID.
    """
    apps = load_applications()
    provider = record.get("provider", {}) or {}

    name = (provider.get("provider_name") or "").strip().lower()
    lic = (provider.get("license_number") or "").strip().lower()

    # Try to find existing entry
    found = None
    for app in apps:
        prov = app.get("provider", {}) or {}
        if (
            prov.get("provider_name", "").strip().lower() == name
            and prov.get("license_number", "").strip().lower() == lic
        ):
            found = app
            break

    # Case 1: update existing record
    if found:
        found.update(record)
        # Ensure id consistency
        if not found.get("id") and found.get("application_id"):
            found["id"] = found["application_id"]
        if not found.get("application_id") and found.get("id"):
            found["application_id"] = found["id"]
        # Ensure not auto-accepted
        found["status"] = record.get("status", "Under Review")
        print(f"🔁 Updated existing record for {name or lic}")

    # Case 2: create new record
    else:
        temp_id = generate_temp_id()
        record["id"] = temp_id  # ✅ grid-compatible
        record["application_id"] = temp_id  # ✅ backend-compatible
        record["status"] = record.get("status", "Under Review")
        record["created_at"] = record.get("created_at", datetime.utcnow().isoformat())
        record.setdefault("documents", [])
        apps.append(record)
        print(f"🆕 Added new record for {name or lic} with ID {temp_id}")

    save_all(apps)

    # Return the record's visible ID (for UI)
    return record.get("id", record.get("application_id", ""))
