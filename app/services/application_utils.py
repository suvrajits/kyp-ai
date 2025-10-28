# app/services/application_utils.py
import json, os
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "applications.json"

def load_applications():
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text())
    except Exception:
        return []

def save_application(record: dict):
    """Append a new record to the persistent JSON file."""
    os.makedirs(DATA_FILE.parent, exist_ok=True)
    apps = load_applications()
    apps.append(record)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2)
    print(f"✅ Application saved. Total records: {len(apps)}")
