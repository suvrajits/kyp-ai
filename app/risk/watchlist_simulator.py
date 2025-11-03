# app/risk/watchlist_simulator.py
import asyncio
import random
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

BASE = Path("app/mock_data/watchlists")
BASE.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "cybersecurity",
    "data_privacy",
    "operational",
    "financial",
    "regulatory",
    "reputation",
    "supplychain",
]

# Simple deterministic-ish generator (seedable)
def _sample_entry(provider_name: str, license_number: str, category: str, idx: int) -> Dict[str, Any]:
    """Return a single watchlist entry object."""
    severity = random.choice([0.3, 0.5, 0.7, 0.9]) if random.random() < 0.25 else random.choice([0.1, 0.2, 0.4])
    return {
        "id": f"{category[:3].upper()}-{idx}-{abs(hash(provider_name)) % 10000}",
        "title": f"Simulated {category} hit #{idx}",
        "detail": f"Auto-generated simulated watchlist entry for {provider_name} ({license_number}).",
        "severity": severity,
        "source": f"simulated_{category}_watchlist",
        "timestamp": datetime.utcnow().isoformat(),
    }

async def simulate_watchlist_call(provider_name: str, license_number: str, category: str, delay_range=(0.05, 0.5)):
    """Simulate an async API call to a watchlist. Returns normalized result dict."""
    # Simulate latency
    await asyncio.sleep(random.uniform(*delay_range))
    # Simulate hit probability
    hit_prob = 0.12  # ~12% chance of 1+ hits (tweakable)
    hits = []
    if random.random() < hit_prob:
        count = random.randint(1, 3)
        for i in range(1, count + 1):
            hits.append(_sample_entry(provider_name, license_number, category, i))

    result = {
        "category": category,
        "hits": len(hits),
        "entries": hits,
        "raw_simulated": {"note": "simulated response"},
    }
    # persist per-provider/category for inspection
    provider_dir = BASE / f"{provider_name}___{license_number}".replace(" ", "_")
    provider_dir.mkdir(parents=True, exist_ok=True)
    file_path = provider_dir / f"{category}.json"
    file_path.write_text(json.dumps(result, indent=2))
    return result
