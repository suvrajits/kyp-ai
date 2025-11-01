# app/services/registry_matcher.py

import json
import os
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

# Path to mock registry
REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "..", "mock_data", "providers.json")


def load_provider_registry() -> List[Dict[str, Any]]:
    """Load provider registry data from JSON file."""
    if not os.path.exists(REGISTRY_FILE):
        print(f"⚠️ Registry file not found at {REGISTRY_FILE}")
        return []
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to load registry: {e}")
        return []


def compute_similarity(a: str, b: str) -> float:
    """Safely compute case-insensitive similarity between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def match_provider(input_fields: Dict[str, str]) -> Tuple[Dict[str, Any], float]:
    """
    Matches extracted input fields against the provider registry.
    Returns the best match and confidence score (0.0–1.0).
    Handles missing fields safely.
    """
    registry = load_provider_registry()
    if not registry:
        print("⚠️ No registry data available.")
        return None, 0.0

    best_match = None
    highest_score = 0.0

    for entry in registry:
        score = 0.0
        total_weight = 0.0

        # Weighted field comparison (name > license > authority)
        if "provider_name" in input_fields and "provider_name" in entry:
            score += compute_similarity(input_fields.get("provider_name"), entry.get("provider_name")) * 0.5
            total_weight += 0.5

        if "license_number" in input_fields and "license_number" in entry:
            score += compute_similarity(input_fields.get("license_number"), entry.get("license_number")) * 0.3
            total_weight += 0.5


        # Normalize score
        if total_weight > 0:
            avg_score = score / total_weight
        else:
            avg_score = 0.0

        # Keep the best match
        if avg_score > highest_score:
            highest_score = avg_score
            best_match = entry

    # Logging summary
    if best_match:
        print(f"✅ Best match found: {best_match.get('provider_name', 'Unknown')} "
              f"({round(highest_score * 100, 1)}% confidence)")
    else:
        print("❌ No matching provider found.")

    return best_match, round(highest_score, 2)


# Example test run
if __name__ == "__main__":
    test_input = {
        "provider_name": "Dr. Ramesh Kumar",
        "license_number": "MH123456789"
    }
    match, score = match_provider(test_input)
    print("Best Match:", match)
    print("Confidence Score:", score)
