import asyncio
import random
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from app.services.application_store import load_applications

# -------------------------------------------------------------------------
# Directory where all watchlist files are stored
# -------------------------------------------------------------------------
BASE = Path("app/mock_data/watchlists")
BASE.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "cybersecurity",
    "data_privacy",
    "financial",
    "operational",
    "regulatory",
    "reputation",
    "supplychain",
]

# =============================================================================
# 🔧 Get provider_name + license_number
# =============================================================================
def get_provider_details(provider_id: str):
    apps = load_applications()
    rec = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None
    )
    if not rec:
        raise ValueError(f"❌ Provider not found: {provider_id}")

    p = rec.get("provider", {})
    return p.get("provider_name", ""), p.get("license_number", "")


# =============================================================================
# 🔧 FULL SIMULATOR (writes JSON files to disk)
# =============================================================================
async def simulate_watchlist(provider_id: str, category: str) -> Dict[str, Any]:
    """
    Main simulator used by orchestrator.
    Generates realistic watchlist entries and writes JSON files per category:
    app/mock_data/watchlists/<provider_id>/<category>.json
    """

    provider_name, license_number = get_provider_details(provider_id)

    # Stable random seed so same provider → consistent results
    random.seed(hash(provider_id + category))

    await asyncio.sleep(random.uniform(0.05, 0.15))

    # 10–15% chance of hits
    entries = []
    if random.random() < 0.15:
        for _ in range(random.randint(1, 3)):
            entries.append({
                "severity": random.choice([0.1, 0.3, 0.5, 0.8]),
                "detail": f"Simulated {category} issue for {provider_name}",
                "timestamp": datetime.utcnow().isoformat(),
                "source": f"simulated_{category}_watchlist"
            })

    note_map = {
        "cybersecurity": "Possible vulnerabilities or threat alerts identified.",
        "data_privacy": "Potential PII exposure or privacy gaps detected.",
        "financial": "Financial irregularities or delays noted.",
        "operational": "Operational disruptions or delays detected.",
        "regulatory": "Compliance or certification issues found.",
        "reputation": "Negative press or sentiment dips observed.",
        "supplychain": "Vendor reliability or delivery issues detected."
    }

    result = {
        "provider_id": provider_id,
        "category": category,
        "hits": len(entries),
        "entries": entries,
        "last_reported": entries[-1]["timestamp"] if entries else None,
        "raw_simulated": {
            "note": note_map.get(category, f"Simulated {category} review.")
        }
    }

    # Ensure directory exists
    provider_dir = BASE / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    # Write category JSON file
    file_path = provider_dir / f"{category}.json"
    file_path.write_text(json.dumps(result, indent=2))

    print(f"📁 [Watchlist Saved] {file_path} — Hits: {len(entries)}")
    return result


# =============================================================================
# 🔧 LIGHTWEIGHT SIMULATOR (FOR PRE-RISK SNAPSHOT ONLY)
# =============================================================================
async def simulate_watchlist_light(provider_name: str, license_number: str, category: str):
    """
    Used only by application_review.py — does NOT write to disk.
    Creates a quick preview risk score per category.
    """

    severities = [0.1, 0.3, 0.5, 0.8]
    entries = []

    # ~30% chance of single simulated hit
    if random.random() < 0.30:
        entries.append({
            "severity": random.choice(severities),
            "detail": f"Simulated preview event in {category}."
        })

    return {
        "category": category,
        "entries": entries,
        "raw_simulated": {
            "note": f"Simulated preview of {category} category."
        },
        "last_reported": datetime.utcnow().isoformat()
    }


# =============================================================================
# 🔧 SIMULATE ALL CATEGORIES (FULL SIMULATOR)
# =============================================================================
async def simulate_all_watchlists(provider_id: str):
    """
    Runs full simulator across all categories.
    Writes JSON files for each category.
    """

    tasks = [
        simulate_watchlist(provider_id, category)
        for category in CATEGORIES
    ]
    return await asyncio.gather(*tasks)
