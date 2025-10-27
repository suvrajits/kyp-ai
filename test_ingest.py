from app.rag.ingest_utils import load_pdf_text, chunk_text, embed_texts
from app.rag.vector_store_faiss import create_faiss_index
import os

pdf_path = "app/mock_data/provider_guidelines.pdf"

# 1️⃣ Extract text from PDF
text = load_pdf_text(pdf_path)
print("✅ Text extracted:")
print(text[:500], "...\n")

# 2️⃣ Chunk text
chunks = chunk_text(text, chunk_size=800, overlap=100)
print(f"✅ Total chunks created: {len(chunks)}")

# 3️⃣ Generate embeddings (using Azure OpenAI)
embeddings = embed_texts(chunks)
print(f"✅ Embeddings shape: {embeddings.shape}")

# 4️⃣ Save to FAISS index
create_faiss_index(embeddings, chunks)
print("🎉 Ingestion complete. FAISS index and chunks.pkl saved.")
