# test_openai_connectivity.py

from openai import AzureOpenAI
from app.config import settings

def test_openai_connections():
    print("🔍 Validating Azure OpenAI configuration...\n")

    # Display key configuration details
    print(f"🔑 Endpoint: {settings.OPENAI_ENDPOINT}")
    print(f"💬 Chat Deployment: {settings.OPENAI_CHAT_DEPLOYMENT}")
    print(f"🧠 Embedding Deployment: {settings.OPENAI_EMBEDDING_DEPLOYMENT}")
    print(f"📦 API Version: {settings.OPENAI_API_VERSION}\n")

    try:
        # Initialize Azure client
        client = AzureOpenAI(
            api_key=settings.OPENAI_KEY,
            api_version=settings.OPENAI_API_VERSION,
            azure_endpoint=settings.OPENAI_ENDPOINT,
        )

        # ---- Test 1: Chat Completion ----
        print("💬 Testing GPT-4o-mini chat deployment...")
        chat_response = client.chat.completions.create(
            model=settings.OPENAI_CHAT_DEPLOYMENT,
            messages=[{"role": "user", "content": "Say 'Azure OpenAI chat test successful!'"}]
        )
        print("✅ Chat Response:", chat_response.choices[0].message.content.strip(), "\n")

        # ---- Test 2: Embeddings ----
        print("🧠 Testing text-embedding-3-small deployment...")
        emb_response = client.embeddings.create(
            input="This is a test sentence for embedding verification.",
            model=settings.OPENAI_EMBEDDING_DEPLOYMENT
        )
        print("✅ Embedding vector length:", len(emb_response.data[0].embedding))

        print("\n🎉 All Azure OpenAI connections are working correctly!")

    except Exception as e:
        print("\n❌ Test failed! Please check your Key Vault secrets or deployments.")
        print("Error:", str(e))

if __name__ == "__main__":
    test_openai_connections()
