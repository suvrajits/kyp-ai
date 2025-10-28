# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Core app modules
from app.rag.ask_api import router as ask_router
from app.rag.router import router as rag_router
from app.routes import (
    upload,
    match,
    analyze_and_match,
    analyze_and_match_html,
    trust_card,
    provider_dashboard,   # ✅ Add dashboard router here
)

# ----------------------------------------------------------
# Initialize FastAPI
# ----------------------------------------------------------
app = FastAPI(
    title="ProviderGPT AI",
    description="An Azure OpenAI-powered intelligent document analysis and retrieval system.",
    version="1.2.0",
)

# ----------------------------------------------------------
# Static Files & Templates (for HTML UI)
# ----------------------------------------------------------
# Mount /static for CSS/JS, optional but safe
app.mount("/static", StaticFiles(directory="static"), name="static")

# ✅ Templates are expected at the project root, not inside app/
templates = Jinja2Templates(directory="templates")

# ----------------------------------------------------------
# Middleware (CORS for frontend use)
# ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Restrict to frontend origin(s) in production
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
# Unified Provider Dashboard (✅ Fix for 404)
# ----------------------------------------------------------
app.include_router(provider_dashboard.router, prefix="/dashboard", tags=["Provider Dashboard"])

# ----------------------------------------------------------
# RAG (Retrieval-Augmented Generation)
# ----------------------------------------------------------
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
        "templates_dir": "templates/ (root-level)",
        "modules": [
            "Upload",
            "Analyze",
            "Match",
            "Trust Card",
            "Provider Dashboard",
            "RAG (Ingest + Ask)",
        ],
    }
