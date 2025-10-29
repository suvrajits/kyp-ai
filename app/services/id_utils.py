# app/services/id_utils.py
import json, os
from pathlib import Path

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
