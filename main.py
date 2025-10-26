# main.py

from fastapi import FastAPI
from app.routes import upload, match, analyze_and_match, analyze_and_match_html, trust_card

app = FastAPI(title="ProviderGPT AI")

# Route registration
app.include_router(upload.router)
app.include_router(match.router)
app.include_router(analyze_and_match.router)
app.include_router(analyze_and_match_html.router)
app.include_router(trust_card.router)