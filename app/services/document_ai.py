# app/services/document_ai.py

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from app.config.settings import AZURE_ENDPOINT, AZURE_KEY

client = DocumentAnalysisClient(
    endpoint=AZURE_ENDPOINT,
    credential=AzureKeyCredential(AZURE_KEY)
)

def analyze_document(file_bytes: bytes):
    """
    Runs Azure Document Intelligence 'prebuilt-document' and returns a dict with:
      - key_value_pairs: [{"key": "...", "value": "..."}]
      - paragraphs: ["...", "..."]
      - raw_text: single concatenated string for downstream regex parsing
    """
    try:
        poller = client.begin_analyze_document("prebuilt-document", document=file_bytes)
        result = poller.result()

        extracted = {}

        kvs = []
        if hasattr(result, "key_value_pairs") and result.key_value_pairs:
            for kv in result.key_value_pairs:
                key = (kv.key.content or "").strip() if kv.key else ""
                value = (kv.value.content or "").strip() if kv.value else ""
                if key or value:
                    kvs.append({"key": key, "value": value})

        paras = []
        if hasattr(result, "paragraphs") and result.paragraphs:
            for p in result.paragraphs:
                if p and p.content:
                    paras.append(p.content.strip())

        extracted["key_value_pairs"] = kvs
        extracted["paragraphs"] = paras

        # Build a convenient raw_text for regex-based parsing downstream
        lines_from_kv = [f"{kv['key']}: {kv['value']}".strip(": ").strip() for kv in kvs if kv.get("key") or kv.get("value")]
        raw_text = " \n".join(lines_from_kv + paras).strip()
        extracted["raw_text"] = raw_text

        return extracted

    except Exception as e:
        raise RuntimeError(f"Document analysis failed: {str(e)}")
