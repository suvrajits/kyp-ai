# app/services/risk_model_client.py
import json
import time
from openai import AzureOpenAI
from typing import Dict, Any, Union
from app.risk.schema import validate_payload

client = None
def init_client(endpoint, api_key, api_version="2024-02-15-preview"):
    global client
    client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
    return client

def call_risk_model(payload: Union[Dict[str, Any], str], model_name: str):
    """
    Accepts either:
     - payload: dict (will be validated via schema)
     - payload: str  (preformatted YAML-style prompt text)
    Returns parsed JSON (dict) when model returns JSON; otherwise raw string.
    """
    # If payload is a dict -> validate
    if isinstance(payload, dict):
        ok, err = validate_payload(payload)
        if not ok:
            raise ValueError(f"Model payload validation failed: {err}")

        # Use JSON as fallback user content
        user_content = json.dumps(payload)

    elif isinstance(payload, str):
        # It's a pre-built text prompt (YAML-like). Skip schema validation.
        user_content = payload

    else:
        raise ValueError("call_risk_model: payload must be dict or str")

    # Logging request
    print("\n\n==================== RISK MODEL REQUEST ====================")
    # print user_content truncated for logs if big
    if isinstance(user_content, str) and len(user_content) > 3000:
        print(user_content[:3000] + "\n...<truncated>")
    else:
        print(user_content)
    print("============================================================\n")

    # Call
    for attempt in range(1, 3):
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a provider risk explanation assistant. RETURN ONLY JSON EXPLAINERS."},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                max_tokens=1200
            )
            raw = resp.choices[0].message.content
            print("\n\n==================== RISK MODEL RAW RESPONSE ====================")
            if len(raw) > 3000:
                print(raw[:3000] + "\n...<truncated>")
            else:
                print(raw)
            print("==================================================================\n")
            # try parse
            try:
                return json.loads(raw)
            except Exception:
                return raw

        except Exception as e:
            print(f"⚠️ Risk model call failed (attempt {attempt}): {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                raise
