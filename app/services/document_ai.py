# app/services/document_ai.py

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from app.config.settings import AZURE_ENDPOINT, AZURE_KEY
import io

client = DocumentAnalysisClient(
    endpoint=AZURE_ENDPOINT,
    credential=AzureKeyCredential(AZURE_KEY)
)

def analyze_document(file_bytes: bytes):
    try:
        poller = client.begin_analyze_document("prebuilt-document", document=file_bytes)
        result = poller.result()

        extracted = {}

        # ✅ Try key-value pairs first (like for invoices or forms)
        if hasattr(result, "key_value_pairs") and result.key_value_pairs:
            kvs = []
            for kv in result.key_value_pairs:
                key = kv.key.content if kv.key else ""
                value = kv.value.content if kv.value else ""
                kvs.append({"key": key, "value": value})
            extracted["key_value_pairs"] = kvs

        # ✅ Also include raw text (fallback for generic documents like certificates)
        paragraphs = [p.content for p in result.paragraphs] if hasattr(result, "paragraphs") else []
        extracted["paragraphs"] = paragraphs

        return extracted

    except Exception as e:
        raise RuntimeError(f"Document analysis failed: {str(e)}")
