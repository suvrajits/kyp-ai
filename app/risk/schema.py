# app/risk/schema.py
from jsonschema import validate, ValidationError

MODEL_PAYLOAD_SCHEMA = {
    "type": "object",
    "required": ["provider_name", "license_number", "watchlist_categories", "web_research", "doc_summary"],
    "properties": {
        "provider_name": {"type": ["string", "null"]},
        "license_number": {"type": "string"},
        "web_research": {"type": "string"},
        "doc_summary": {"type": "string"},
        "watchlist_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "hits", "entries", "note"],
                "properties": {
                    "category": {"type": "string"},
                    "hits": {"type": ["integer", "null"]},
                    "entries": {
                        "type": "array",
                        "items": {"type": "object"}
                    },
                    "note": {"type": "string"}
                }
            }
        }
    }
}

def validate_payload(payload: dict):
    try:
        validate(instance=payload, schema=MODEL_PAYLOAD_SCHEMA)
        return True, None
    except ValidationError as e:
        return False, str(e)
