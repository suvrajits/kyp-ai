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


def _sample_entry(provider_name: str, license_number: str, category: str, idx: int) -> Dict[str, Any]:
    """Return a single watchlist entry object with realistic details."""
    severity = random.choice([0.3, 0.5, 0.7, 0.9]) if random.random() < 0.25 else random.choice([0.1, 0.2, 0.4])
    titles = {
        "financial": [
            "Delayed GST filing",
            "Auditor remark on working capital",
            "Minor discrepancy in annual report"
        ],
        "cybersecurity": [
            "Endpoint vulnerability scan alert",
            "Firewall misconfiguration found",
            "Breach notification in vendor network"
        ],
        "data_privacy": [
            "PII exposure alert",
            "GDPR compliance gap report",
            "Unauthorized access incident"
        ],
        "operational": [
            "Operational delay in diagnostics unit",
            "Service downtime detected",
            "Vendor supply delay event"
        ],
        "regulatory": [
            "Expired state license flag",
            "Pending statutory renewal",
            "Compliance documentation missing"
        ],
        "reputation": [
            "Negative press mention detected",
            "Public review anomaly found",
            "Social sentiment dip"
        ],
        "supplychain": [
            "Vendor reliability drop",
            "Delivery backlog in supplies",
            "Supplier compliance issue"
        ]
    }

    title = random.choice(titles.get(category, [f"Simulated {category} hit"]))
    return {
        "id": f"{category[:3].upper()}-{idx}-{abs(hash(provider_name)) % 10000}",
        "title": title,
        "detail": f"Simulated event for {provider_name} ({license_number}).",
        "severity": severity,
        "source": f"simulated_{category}_watchlist",
        "timestamp": datetime.utcnow().isoformat(),
    }


async def simulate_watchlist_call(provider_name: str, license_number: str, category: str, delay_range=(0.05, 0.5)):
    """Simulate an async API call to a watchlist."""
    random.seed(hash(provider_name + license_number + category))  # ✅ Stable randomness per provider
    await asyncio.sleep(random.uniform(*delay_range))

    hit_prob = 0.12  # 12% chance of hits
    hits = []
    if random.random() < hit_prob:
        count = random.randint(1, 3)
        for i in range(1, count + 1):
            hits.append(_sample_entry(provider_name, license_number, category, i))

    last_reported = hits[-1]["timestamp"] if hits else None
    notes = {
        "financial": "Financial discrepancies or delayed statutory filings noted in public or regulatory databases.",
        "cybersecurity": "Potential vulnerabilities detected in external systems or breach notifications from security intelligence sources.",
        "data_privacy": "Possible data privacy compliance gaps or exposure incidents identified through open datasets.",
        "operational": "Operational continuity or service disruption reports identified through third-party audits.",
        "regulatory": "Non-compliance alerts or expired certifications detected in state health registries.",
        "reputation": "Negative public sentiment or adverse media coverage observed in recent monitoring cycles.",
        "supplychain": "Vendor reliability issues or dependency risks found in procurement and logistics reports."
    }

    result = {
        "category": category,
        "hits": len(hits),
        "entries": hits,
        "last_reported": last_reported,
        "raw_simulated": {"note": notes.get(category, "Simulated response")},
    }

    provider_dir = BASE / f"{provider_name}___{license_number}".replace(" ", "_")
    provider_dir.mkdir(parents=True, exist_ok=True)
    file_path = provider_dir / f"{category}.json"
    file_path.write_text(json.dumps(result, indent=2))
    return result


async def simulate_all_watchlists(provider_name: str, license_number: str):
    """Load or simulate all 7 category watchlists for the given provider."""
    provider_dir = BASE / f"{provider_name}___{license_number}".replace(" ", "_")
    provider_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for category in CATEGORIES:
        file_path = provider_dir / f"{category}.json"

        if file_path.exists():
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                    print(f"📂 [Watchlist] {category}: {len(data.get('entries', []))} hit(s) loaded from existing file.")
                    results.append(data)
                    continue
            except Exception as e:
                print(f"⚠️ Failed to read {file_path}: {e}")

        simulated = await simulate_watchlist_call(provider_name, license_number, category)
        print(f"📂 [Watchlist] {category}: {len(simulated.get('entries', []))} hit(s) generated via simulation.")
        results.append(simulated)

    return results
