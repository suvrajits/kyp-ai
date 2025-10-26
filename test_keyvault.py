# test_keyvault.py

from app.config import settings

def main():
    print("✅ Azure Form Recognizer Endpoint:", settings.AZURE_ENDPOINT)
    print("✅ Azure Form Recognizer Key:", settings.AZURE_KEY[:10] + "…")  # Masked for safety

if __name__ == "__main__":
    main()
