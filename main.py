# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
from dotenv import load_dotenv
import os

# ----------------------------------------------------------
# 🌐 Import Core Modules
# ----------------------------------------------------------
from app.rag.ask_api import router as ask_router
from app.rag.router import router as rag_router
from app.routes import (
    upload,
    match,
    analyze_and_match,
    analyze_and_match_html,
    trust_card,
    provider_dashboard,
    application_review,
    search,
    review,
)

# Explicitly load the .env from app/config
dotenv_path = os.path.join(os.path.dirname(__file__), "app", "config", ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    print(f"✅ Loaded .env from: {dotenv_path}")
else:
    print(f"⚠️ .env file not found at {dotenv_path}")
    
# ----------------------------------------------------------
# 🚀 Initialize FastAPI App
# ----------------------------------------------------------
app = FastAPI(
    title="ProviderGPT AI",
    description=(
        "An Azure OpenAI–powered intelligent document analysis and provider "
        "verification system integrating OCR, Registry Matching, and RAG search."
    ),
    version="1.4.0",
)

# ----------------------------------------------------------
# 🗂️ Templates & Static Files
# ----------------------------------------------------------
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    print("⚠️  Skipping /static mount — directory not found.")

templates = Jinja2Templates(directory="templates")

# ----------------------------------------------------------
# 🔒 CORS Middleware
# ----------------------------------------------------------
# ⚠️ In production, replace ["*"] with your frontend’s domain(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------
# 🧩 Include All Routers
# ----------------------------------------------------------
# Document / Upload / Analyze
app.include_router(upload.router, prefix="/upload", tags=["Upload & Intake"])
app.include_router(match.router, prefix="/match", tags=["Registry Matching"])
app.include_router(analyze_and_match.router, prefix="/analyze", tags=["Text Analysis"])
app.include_router(analyze_and_match_html.router, prefix="/analyze-html", tags=["UI Analysis"])

# Dashboard & Trust
app.include_router(provider_dashboard.router, prefix="/dashboard", tags=["Provider Dashboard"])
app.include_router(trust_card.router, prefix="/trust-card", tags=["Trust Card Generation"])

# RAG (Retrieval-Augmented Generation)
app.include_router(rag_router, prefix="/rag", tags=["RAG - Ingest"])
app.include_router(ask_router, prefix="/rag", tags=["RAG - Ask"])

# Application Review
app.include_router(application_review.router, prefix="", tags=["Application Review"])

# 🔍 Smart Semantic Search
app.include_router(search.router, prefix="/search", tags=["Semantic Search"])  # ✅ NEW

app.include_router(review.router)

# ----------------------------------------------------------
# 🧠 Startup / Shutdown Events
# ----------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    print("\n" + "=" * 90)
    print("🚀 PROVIDER GPT BACKEND STARTED")
    print(f"🕒 {datetime.utcnow().isoformat()} UTC")
    print("📂 Active Modules:")
    print("   • Upload / Analyze / Match")
    print("   • Provider Dashboard")
    print("   • Trust Card Generator")
    print("   • RAG (Ask + Ingest)")
    print("   • Smart Semantic Search  ✅")
    print("=" * 90 + "\n")

@app.on_event("shutdown")
async def on_shutdown():
    print("🧩 Graceful shutdown: releasing any in-memory state / connections.")

# ----------------------------------------------------------
# 🩺 Health Check Route
# ----------------------------------------------------------
@app.get("/", tags=["Health"])
def root():
    """Simple health check and app summary."""
    return {
        "ok": True,
        "app_name": "ProviderGPT AI",
        "version": "1.4.0",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "✅ ProviderGPT backend is up and running.",
        "modules_loaded": [
            "Upload & Intake",
            "Analyze (Document AI + Parser)",
            "Registry Matching",
            "Provider Dashboard",
            "Trust Card Generator",
            "RAG (Ingest & Ask)",
            "Smart Semantic Search",
        ],
        "template_dir": "templates/",
        "data_dir": "app/data/",
    }
