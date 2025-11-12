import json
import re
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI

# =========================
# 🔐 1️⃣ Load from Key Vault
# =========================
KEY_VAULT_URL = "https://providergpt-kv.vault.azure.net/"  # 👈 replace with your actual vault URI

# Use DefaultAzureCredential (works locally via `az login` or in Azure App Service)
credential = DefaultAzureCredential()
secret_client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)

# Fetch secrets
risk_model_endpoint = secret_client.get_secret("riskModelEndpoint").value
risk_model_key = secret_client.get_secret("riskModelKey").value

# =========================
# 🤖 2️⃣ Initialize OpenAI Client
# =========================
client = AzureOpenAI(
    azure_endpoint=risk_model_endpoint,
    api_key=risk_model_key,
    api_version="2024-02-15-preview"
)

# =========================
# 🧠 3️⃣ Run Risk Evaluation
# =========================
messages = [
    {
        "role": "system",
        "content": (
            "You are a financial risk evaluation assistant that predicts "
            "category-wise risks and an overall aggregated risk score based on user data. "
            "Always output only valid JSON with keys: category_scores, aggregated_score, "
            "risk_level, and confidence."
        )
    },
    {
        "role": "user",
        "content": """Category-wise risk factors:
provider_name: Global Pharma Alliance
license_number: LIC-8821
watchlists:
- cybersecurity: 1 hits: ['Endpoint compromise contained within 24 hours (severity 0.4)']
- data_privacy: 1 hits: ['Outdated GDPR policy; updated post-audit (severity 0.3)']
- operational: 2 hits: ['Factory downtime due to flood (severity 0.8)', 'Temporary logistics disruption (severity 0.6)']
- financial: 1 hits: ['Exchange rate impact on procurement (severity 0.4)']
- regulatory: 2 hits: ['Minor labeling violation (severity 0.4)', 'Documentation delay for new product (severity 0.3)']
- reputation: 1 hits: ['Positive media coverage for disaster response (severity 0.1)']
- supplychain: 2 hits: ['Raw material shortage (severity 0.5)', 'Backup supplier under evaluation (severity 0.4)']
web_research: 'Balanced feedback: strong recovery actions praised.'
doc_summary: 'All audit issues addressed; follow-up due next quarter.'
Produce JSON as specified."""
    },
]

response = client.chat.completions.create(
    model="gpt-4o-mini-2024-07-18-risk-eval-v2",
    messages=messages,
    temperature=0.2,
    max_tokens=1024
)

# =========================
# 📊 4️⃣ Parse Model Output
# =========================
try:
    result = json.loads(response.choices[0].message.content)
    print(json.dumps(result, indent=2))
except json.JSONDecodeError:
    print("⚠️ Model output was not valid JSON:")
    print(response.choices[0].message.content)
