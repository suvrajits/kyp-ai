# app/risk/payload_builder.py
import json
from pathlib import Path
from app.services.application_store import load_applications

# Real location of watchlist data
BASE_WATCHLIST_DIR = Path("app/mock_data/watchlists")

CANONICAL = [
    "cybersecurity",
    "data_privacy",
    "financial",
    "operational",
    "regulatory",
    "reputation",
    "supplychain",
]


def load_watchlist_json(provider_id: str, category: str):
    """
    Loads the JSON file:
        app/mock_data/watchlists/<provider_id>/<category>.json

    Returns:
        {
            "entries": [...],
            "note": "...",
            "hits": int
        }
    """

    folder = BASE_WATCHLIST_DIR / provider_id
    file = folder / f"{category}.json"

    if not file.exists():
        print(f"⚠️ No watchlist file for provider='{provider_id}' category='{category}' → {file}")
        return {"entries": [], "note": "", "hits": 0}

    try:
        raw = json.loads(file.read_text())

        # Most of your real JSON files contain a list of entries directly
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict) and "entries" in raw:
            entries = raw["entries"]
        else:
            entries = []

        hits = len(entries)

        # Extract best possible note
        def extract_note(entry):
            return (
                entry.get("Note")
                or entry.get("RiskNote")
                or entry.get("Detail")
                or entry.get("Description")
                or entry.get("Title")
                or ""
            )

        note = extract_note(entries[0]) if entries else ""

        # DEBUG LOG
        print(f"\n=== WATCHLIST READ: provider={provider_id} category={category} ===")
        print(f"File: {file}")
        print(f"Hits: {hits}")
        print(f"Note: {note[:200]}")
        print("Entries preview:", json.dumps(entries[:2], indent=2))
        print("=========================================================\n")

        return {
            "entries": entries,
            "note": note,
            "hits": hits,
        }

    except Exception as e:
        print(f"❌ ERROR reading watchlist at {file}: {e}")
        return {"entries": [], "note": "", "hits": 0}


def build_model_payload(provider_id: str):
    """
    Builds the final payload sent to the Risk Model.
    """

    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None
    )
    if not record:
        raise ValueError(f"No provider record found for {provider_id}")

    provider = record.get("provider", {})
    provider_name = provider.get("provider_name", "Unknown Provider")
    license_number = provider.get("license_number", "N/A")

    web_research = record.get("web_research", "No web research available.")
    doc_summary = record.get("doc_summary", "No document summary available.")

    watchlist_categories = []

    for category in CANONICAL:
        wl = load_watchlist_json(provider_id, category)

        watchlist_categories.append({
            "category": category,
            "hits": wl["hits"],
            "entries": wl["entries"],
            "note": wl["note"],
        })

    payload = {
        "provider_name": provider_name,
        "license_number": license_number,
        "web_research": web_research,
        "doc_summary": doc_summary,
        "watchlist_categories": watchlist_categories,
    }

    # FINAL DEBUG LOG
    print("\n======= FINAL PAYLOAD TO RISK MODEL =======")
    print(json.dumps(payload, indent=2)[:3000])
    print("==========================================\n")

    return payload
