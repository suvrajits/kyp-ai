# app/services/embedding_utils.py
from __future__ import annotations
import os, numpy as np, faiss, traceback, hashlib
from openai import AzureOpenAI

# ============================================================
# ⚙️ Global Configuration
# ============================================================
USE_AZURE = os.getenv("USE_AZURE", "0") == "1"  # Toggle via .env
_keyvault_cache = {}
_embed_cache: dict[str, np.ndarray] = {}  # In-memory embedding cache


# ============================================================
# 🔐 Secret Loader (Env → Azure Key Vault fallback)
# ============================================================
def get_secret(secret_name: str) -> str | None:
    """
    Loads secret from environment first. If USE_AZURE=1, attempts Key Vault fallback.
    """
    env_key = os.getenv(secret_name.upper())
    if env_key:
        print(f"🔑 Using environment secret for '{secret_name}'")
        return env_key

    if not USE_AZURE:
        print(f"🧠 Local FAISS mode — skipping Azure lookup for '{secret_name}'")
        return None

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        key_vault_name = os.getenv("KEYVAULT_NAME") or os.getenv("KEY_VAULT_NAME")
        if not key_vault_name:
            raise RuntimeError("❌ Missing KEYVAULT_NAME or KEY_VAULT_NAME env variable.")

        kv_uri = f"https://{key_vault_name}.vault.azure.net"
        credential = DefaultAzureCredential(additionally_allowed_tenants=["*"])
        client = SecretClient(vault_url=kv_uri, credential=credential)

        if secret_name in _keyvault_cache:
            return _keyvault_cache[secret_name]

        secret = client.get_secret(secret_name)
        _keyvault_cache[secret_name] = secret.value
        print(f"🟢 Retrieved '{secret_name}' from Azure Key Vault")
        return secret.value

    except Exception as e:
        print(f"⚠️ Key Vault lookup failed for '{secret_name}': {e}")
        traceback.print_exc()
        return None


# ============================================================
# 🧩 Deterministic Local Embeddings (FAISS-compatible)
# ============================================================
def _deterministic_embedding(text: str, dim: int = 1536) -> np.ndarray:
    """
    Generates a deterministic and semantically separated embedding for offline FAISS use.
    Ensures that unrelated texts have low similarity while same texts stay identical.
    """
    text = text.strip().lower()

    # Stable base seed from text hash
    seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.normal(0, 1, dim).astype("float32")

    # Create stronger text bias across full dimension
    bias_bytes = hashlib.sha512(text.encode("utf-8")).digest()
    repeats = (dim // len(bias_bytes)) + 1
    bias = np.frombuffer(bias_bytes * repeats, dtype=np.uint8)[:dim].astype("float32")
    bias = (bias - np.mean(bias)) / np.std(bias)  # normalize to mean 0

    # Combine random + bias components with stronger weighting on bias
    vec = 0.4 * vec + 0.6 * bias
    vec = vec.astype("float32")

    # Normalize for FAISS
    faiss.normalize_L2(vec.reshape(1, -1))
    return vec




def _random_embeddings(n: int, dim: int = 1536) -> np.ndarray:
    """
    Legacy random embeddings (non-deterministic). Only used if deterministic mode fails.
    """
    rng = np.random.default_rng(seed=42)
    vectors = rng.random((n, dim), dtype="float32")
    faiss.normalize_L2(vectors)
    return vectors


# ============================================================
# 🧠 Embedding Wrappers
# ============================================================
def embed_texts(texts: list[str]) -> np.ndarray:
    """
    Generates embeddings for a batch of texts using Azure or deterministic FAISS fallback.
    """
    if not texts:
        return np.array([])

    # Try Azure first if enabled
    if USE_AZURE:
        client = get_azure_openai_client()
        if client:
            try:
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                )
                vectors = [np.array(e.embedding, dtype="float32") for e in response.data]
                vectors = np.vstack(vectors)
                faiss.normalize_L2(vectors)
                return vectors
            except Exception as e:
                print(f"⚠️ Azure embedding failed, switching to local mode: {e}")

    # Local deterministic embeddings
    try:
        vectors = np.vstack([_deterministic_embedding(t) for t in texts])
        return vectors
    except Exception as e:
        print(f"⚠️ Deterministic embedding failed, using random fallback: {e}")
        return _random_embeddings(len(texts))


def embed_single_text(text: str) -> np.ndarray:
    """
    Embeds a single text into a normalized 1536-dim vector.
    """
    if not text:
        return np.zeros((1536,), dtype="float32")
    return embed_texts([text])[0]


# ============================================================
# 🌐 Azure OpenAI Client Factory
# ============================================================
def get_azure_openai_client() -> AzureOpenAI | None:
    """
    Returns Azure OpenAI client if USE_AZURE=1 and credentials are valid.
    """
    if not USE_AZURE:
        print("🧠 Running in Local FAISS mode — Azure OpenAI disabled.")
        return None

    try:
        api_key = get_secret("azure-openai-api-key")
        endpoint = get_secret("azure-openai-endpoint")

        if not api_key or not endpoint:
            print("⚠️ Missing Azure OpenAI credentials. Falling back to local mode.")
            return None

        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
        )
        print("✅ Azure OpenAI client initialized (USE_AZURE=1).")
        return client

    except Exception as e:
        print(f"⚠️ Azure client unavailable: {e}")
        traceback.print_exc()
        return None


# ============================================================
# 🚀 Batch Embedding Helper
# ============================================================
def embed_text_batch(texts: list[str], batch_size: int = 8) -> np.ndarray:
    """
    Efficiently embeds a list of text chunks in batches.
    Includes in-memory cache and deterministic fallback for FAISS mode.
    """
    if not texts:
        return np.array([])

    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_vecs = []

        # Use cache to avoid re-embedding identical text
        uncached_texts = []
        for t in batch:
            key = hashlib.md5(t.encode("utf-8")).hexdigest()
            if key in _embed_cache:
                batch_vecs.append(_embed_cache[key])
            else:
                uncached_texts.append(t)

        if uncached_texts:
            new_vecs = embed_texts(uncached_texts)
            for t, v in zip(uncached_texts, new_vecs):
                key = hashlib.md5(t.encode("utf-8")).hexdigest()
                _embed_cache[key] = v
                batch_vecs.append(v)

        batch_vecs = np.vstack(batch_vecs)
        all_vecs.append(batch_vecs)

    final_vecs = np.vstack(all_vecs)
    faiss.normalize_L2(final_vecs)
    return final_vecs
