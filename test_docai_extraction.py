import os
from app.services.azure_docai_extractor import AzureDocumentExtractor

# Your Key Vault URL
VAULT_URL = "https://providergpt-kv.vault.azure.net/"

# Path to your PDF
PDF_PATH = r"C:\Users\suvra\OneDrive\Desktop\Resume\Portfolio\Healthcare\New_provider_pdfs\provider_58.pdf"

# Initialize the Document Extractor
extractor = AzureDocumentExtractor(vault_url=VAULT_URL)

# Perform extraction
print("🔍 Starting extraction...\n")
fields = extractor.extract_from_pdf(PDF_PATH)

print("\n✅ Extraction Complete! Extracted fields:")
for key, value in fields.items():
    print(f"{key:35}: {value}")
