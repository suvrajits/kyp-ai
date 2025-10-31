import os
import logging
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.ai.formrecognizer import DocumentAnalysisClient, DocumentAnalysisApiVersion
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ClientAuthenticationError

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class AzureDocumentExtractor:
    """
    Azure Document Intelligence client wrapper.
    - Securely fetches endpoint, key, and model ID from Azure Key Vault.
    - Sends PDFs for analysis to the trained custom model.
    - Returns extracted fields as a Python dictionary.
    """

    def __init__(self, vault_url: str):
        try:
            # Initialize credential and Key Vault client
            self.credential = DefaultAzureCredential()
            self.secret_client = SecretClient(vault_url=vault_url, credential=self.credential)

            # Retrieve secrets — aligned with your Key Vault naming scheme
            self.endpoint = self._get_secret("formRecognizerEndpoint")
            self.api_key = self._get_secret("formRecognizerKey")
            self.model_id = self._get_secret("formRecognizerModelId")

            # Resolve API version safely
            api_version_str = self._get_secret("formRecognizerApiVersion", default="2023-07-31")
            self.api_version = self._resolve_api_version(api_version_str)

            # Initialize Azure Document Intelligence client
            self.client = DocumentAnalysisClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.api_key),
                api_version=self.api_version
            )

            logger.info(f"✅ AzureDocumentExtractor initialized using model: {self.model_id}")

        except ClientAuthenticationError as e:
            logger.error(f"❌ Azure Key Vault authentication failed: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to initialize AzureDocumentExtractor: {e}")
            raise

    def _resolve_api_version(self, version_str: str):
        """
        Maps a version string to a supported SDK enum.
        """
        supported = {
            "2023-07-31": DocumentAnalysisApiVersion.V2023_07_31,
            "2022-08-31": DocumentAnalysisApiVersion.V2022_08_31,
        }

        if version_str not in supported:
            logger.warning(
                f"⚠️ Unsupported API version '{version_str}', falling back to 2023-07-31."
            )
        return supported.get(version_str, DocumentAnalysisApiVersion.V2023_07_31)

    def _get_secret(self, name: str, default: str = None) -> str:
        """
        Safely fetch a secret from Key Vault or fallback to env var.
        """
        try:
            secret = self.secret_client.get_secret(name).value
            if not secret:
                raise ValueError(f"Secret '{name}' is empty.")
            return secret
        except Exception as e:
            logger.warning(f"⚠️ Could not retrieve '{name}' from Key Vault: {e}")
            env_fallback = os.getenv(name.upper())
            if env_fallback:
                logger.info(f"✅ Using environment fallback for '{name}'")
                return env_fallback
            elif default is not None:
                logger.info(f"⚙️ Using default value for '{name}'")
                return default
            else:
                raise ValueError(f"Secret '{name}' not found in Key Vault or env vars.")

    def extract_from_pdf(self, file_path: str) -> dict:
        """
        Send a PDF to Azure Document Intelligence and return extracted field-value pairs.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "rb") as f:
                logger.info(f"📤 Analyzing document with model '{self.model_id}' ...")
                poller = self.client.begin_analyze_document(model_id=self.model_id, document=f)
                result = poller.result()

            extracted = {}
            for doc in result.documents:
                for name, field in doc.fields.items():
                    extracted[name] = field.value if field.value else None

            logger.info(f"✅ Extraction complete. Fields found: {len(extracted)}")
            return extracted

        except HttpResponseError as e:
            logger.error(f"❌ Document analysis failed (HTTP error): {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error during document extraction: {e}")
            raise
