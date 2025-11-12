# app/services/risk_model_client.py

import json
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI

KEY_VAULT_URL = "https://providergpt-kv.vault.azure.net/"
credential = DefaultAzureCredential()
secret_client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)

RISK_MODEL_ENDPOINT = secret_client.get_secret("riskModelEndpoint").value
RISK_MODEL_KEY = secret_client.get_secret("riskModelKey").value

client = AzureOpenAI(
    azure_endpoint=RISK_MODEL_ENDPOINT,
    api_key=RISK_MODEL_KEY,
    api_version="2024-02-15-preview",
)

async def call_risk_model(payload: dict) -> dict:
    """
    Calls the fine-tuned risk model and returns structured JSON.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial risk evaluation assistant that predicts "
                "category-wise risks and an overall aggregated risk score based on user data. "
                "Always output valid JSON with these keys: "
                "category_scores (each must contain {score: <0-100>, note: <textual reasoning>}), "
                "aggregated_score, risk_level, and confidence. "
                "The 'note' field must summarize the reason for each risk score clearly."
            ),
        },
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini-2024-07-18-risk-eval-v2",
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
    )

    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(f"Model did not return valid JSON:\n{content}")
