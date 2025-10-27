# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Core app modules
from app.rag.ask_api import router as ask_router
from app.rag.router import router as rag_router
from app.routes import upload, match, analyze_and_match, analyze_and_match_html, trust_card

# ----------------------------------------------------------
# Initialize FastAPI
# ----------------------------------------------------------
app = FastAPI(
    title="ProviderGPT AI",
    description="An Azure OpenAI-powered intelligent document analysis and retrieval system.",
    version="1.0.0"
)

# ----------------------------------------------------------
# Middleware (CORS for frontend use)
# ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Change to frontend origin(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------
# Core business logic routes
# ----------------------------------------------------------
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(match.router, prefix="/match", tags=["Matching"])
app.include_router(analyze_and_match.router, prefix="/analyze", tags=["Analysis"])
app.include_router(analyze_and_match_html.router, prefix="/analyze-html", tags=["HTML Analysis"])
app.include_router(trust_card.router, prefix="/trust-card", tags=["Trust Cards"])

# ----------------------------------------------------------
# RAG (Retrieval-Augmented Generation) module
# ----------------------------------------------------------
# ✅ These two are the only correct registrations.
# DO NOT add prefix again inside ask_api.py or router.py
app.include_router(rag_router, prefix="/rag", tags=["RAG - Ingest"])
app.include_router(ask_router, prefix="/rag", tags=["RAG - Ask"])

# ----------------------------------------------------------
# Health Check
# ----------------------------------------------------------
@app.get("/", tags=["Health"])
def root():
    return {
        "ok": True,
        "app": "ProviderGPT AI",
        "message": "✅ ProviderGPT backend is up and running.",
        "modules": ["RAG", "Upload", "Match", "Analyze", "Trust Card"]
    }
