# app/services/registry_matcher.py

import json
import os
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "..", "mock_data", "providers.json")

def load_provider_registry() -> List[Dict[str, Any]]:
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def compute_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def match_provider(input_fields: Dict[str, str]) -> Tuple[Dict[str, Any], float]:
    """
    Matches the extracted input fields against the provider registry and returns
    the best match with a confidence score (0.0 to 1.0).
    """
    registry = load_provider_registry()
    best_match = None
    highest_score = 0.0

    for entry in registry:
        score = 0
        total_fields = 0

        if "provider_name" in input_fields and "provider_name" in entry:
            score += compute_similarity(input_fields["provider_name"], entry["provider_name"])
            total_fields += 1

        if "license_number" in input_fields and "license_number" in entry:
            score += compute_similarity(input_fields["license_number"], entry["license_number"])
            total_fields += 1

        if "issuing_authority" in input_fields and "issuing_authority" in entry:
            score += compute_similarity(input_fields["issuing_authority"], entry["issuing_authority"])
            total_fields += 1

        if total_fields > 0:
            avg_score = score / total_fields
            if avg_score > highest_score:
                highest_score = avg_score
                best_match = entry

    return best_match, round(highest_score, 2)

# Example usage
if __name__ == "__main__":
    test_input = {
        "provider_name": "Dr. Ramesh Kumar",
        "license_number": "MH123456789",
        "issuing_authority": "Maharashtra Medical Council"
    }
    match, score = match_provider(test_input)
    print("Best Match:", match)
    print("Confidence Score:", score)
