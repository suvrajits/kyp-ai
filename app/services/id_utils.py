# app/services/id_utils.py
import json, os
from pathlib import Path
from datetime import datetime

# Counter file location
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
COUNTER_FILE = DATA_DIR / "application_counter.json"
os.makedirs(DATA_DIR, exist_ok=True)

def load_counter() -> dict:
    """Load or initialize counter for TEMP-ID tracking."""
    if not COUNTER_FILE.exists():
        return {"last_temp_id": 0}
    try:
        return json.loads(COUNTER_FILE.read_text())
    except Exception:
        return {"last_temp_id": 0}

def save_counter(counter: dict):
    """Persist counter updates."""
    COUNTER_FILE.write_text(json.dumps(counter, indent=2))

def generate_temp_id() -> str:
    """Generate incremental TEMP-ID-### string."""
    counter = load_counter()
    counter["last_temp_id"] = counter.get("last_temp_id", 0) + 1
    save_counter(counter)
    return f"TEMP-ID-{counter['last_temp_id']:03d}"

def generate_app_id() -> str:
    """Generate permanent Application ID in the format APP-YYYYMMDD-#####."""
    today = datetime.utcnow().strftime("%Y%m%d")
    counter_path = DATA_DIR / "application_counter.json"

    counter = {}
    if counter_path.exists():
        try:
            counter = json.loads(counter_path.read_text())
        except Exception:
            counter = {}
    last_count = counter.get("last_app_id", 0) + 1
    counter["last_app_id"] = last_count
    counter_path.write_text(json.dumps(counter, indent=2))

    return f"APP-{today}-{last_count:05d}"
