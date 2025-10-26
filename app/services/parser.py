# app/services/parser.py

def parse_provider_license(extracted: dict) -> dict:
    kv_pairs = extracted.get("key_value_pairs", [])

    structured = {
        "provider_name": None,
        "license_number": None,
        "specialty": None,
        "issuing_authority": None,
        "issue_date": None,
        "expiry_date": None
    }

    key_map = {
        "name of provider": "provider_name",
        "license number": "license_number",
        "specialty": "specialty",
        "issuing authority": "issuing_authority",
        "issue date": "issue_date",
        "expiry date": "expiry_date"
    }

    for pair in kv_pairs:
        raw_key = pair.get("key", "").lower().strip().replace(":", "")
        raw_value = pair.get("value", "").strip()

        for match, target_field in key_map.items():
            if match in raw_key:
                structured[target_field] = raw_value

    return structured
