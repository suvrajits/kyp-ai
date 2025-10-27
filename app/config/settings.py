# app/config/settings.py

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import os

# 1. Vault URL from environment variable (or fallback)
VAULT_URL = os.getenv("AZURE_KEY_VAULT_URI", "https://providergpt-kv.vault.azure.net/")

# 2. Azure credential - auto-auth from CLI, VS Code, or managed identity
credential = DefaultAzureCredential()

# 3. Create Key Vault client
client = SecretClient(vault_url=VAULT_URL, credential=credential)

# 4. Load secrets
try:
    AZURE_ENDPOINT = client.get_secret("formRecognizerEndpoint").value
    AZURE_KEY = client.get_secret("formRecognizerKey").value

        # ---- Azure OpenAI ----
    OPENAI_ENDPOINT = client.get_secret("openaiEndpoint").value
    OPENAI_KEY = client.get_secret("openaiKey").value
    OPENAI_API_VERSION = client.get_secret("openaiApiVersion").value
    OPENAI_CHAT_DEPLOYMENT = client.get_secret("openaiChatDeployment").value
    OPENAI_EMBEDDING_DEPLOYMENT = client.get_secret("openaiEmbeddingDeployment").value
except Exception as e:
    raise RuntimeError("Failed to load Azure Form Recognizer credentials: " + str(e))

