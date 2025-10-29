# app/routes/application_review.py

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.services.application_store import load_applications, save_all
from datetime import datetime
from pathlib import Path
from shutil import move, copytree, rmtree
from app.services.id_utils import generate_app_id

router = APIRouter()

# ✅ Templates path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ============================================================
# 🟢 1️⃣ Review Page – Display Application for Analyst
# ============================================================
@router.get("/review/{app_id}", response_class=HTMLResponse)
async def review_application(request: Request, app_id: str):
    """Render the application review page for a 'New' application."""
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)

    if not record:
        return HTMLResponse(f"<h3>❌ No application found for ID: {app_id}</h3>", status_code=404)

    # If already promoted or not new, redirect to dashboard
    if record.get("status") not in ["New", "Pending"]:
        return RedirectResponse(f"/dashboard/view/{record.get('id')}", status_code=303)

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
        },
    )


# ============================================================
# 🟢 2️⃣ Accept Application → Move to Provider Stage
# ============================================================
@router.post("/review/{app_id}/accept")
async def accept_application(request: Request, app_id: str):
    """
    Accept an incoming application.
    Promotes TEMP-ID → APP-ID, migrates FAISS directory if present,
    builds FAISS embeddings for the license text, and redirects to dashboard.
    """
    from shutil import move, copytree, rmtree
    from app.services.id_utils import generate_app_id
    from app.rag.ingest import embed_texts
    from app.rag.vector_store_faiss import save_faiss_index
    import faiss
    import numpy as np

    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    # 🚧 Prevent double acceptance
    if record.get("id", "").startswith("APP-"):
        print(f"⚠️ Application {app_id} already promoted → {record['id']}")
        return RedirectResponse(url=f"/dashboard/view/{record['id']}", status_code=303)

    # ✅ Generate new APP-ID
    new_app_id = generate_app_id()
    print(f"🔁 Promoting {app_id} → {new_app_id}")

    # --------------------------------------------------------
    # 🗂️ Move FAISS directory safely
    # --------------------------------------------------------
    old_faiss_dir = Path("app/data/faiss_store") / app_id
    new_faiss_dir = Path("app/data/faiss_store") / new_app_id
    try:
        if old_faiss_dir.exists():
            move(str(old_faiss_dir), str(new_faiss_dir))
            print(f"📦 Moved FAISS data from {old_faiss_dir.name} → {new_faiss_dir.name}")
        else:
            print(f"ℹ️ No FAISS directory found for {app_id}, skipping move.")
    except Exception as e:
        print(f"⚠️ Could not move FAISS folder ({app_id}): {e}")

    # --------------------------------------------------------
    # 🧩 Promote and Normalize Record
    # --------------------------------------------------------
    record["id"] = new_app_id
    record["application_id"] = new_app_id
    record["status"] = "Under Review"

    # --------------------------------------------------------
    # 🧠 Create FAISS index for extracted license text
    # --------------------------------------------------------
    try:
        provider = record.get("provider", {})
        if provider:
            text_data = "\n".join([f"{k}: {v}" for k, v in provider.items() if v])
            print(f"🧠 Creating FAISS embeddings for structured license data ({len(text_data.split())} tokens)...")

            vectors = embed_texts([text_data])
            faiss.normalize_L2(vectors)

            provider_dir = Path("app/data/faiss_store") / new_app_id
            provider_dir.mkdir(parents=True, exist_ok=True)

            save_faiss_index(
                vectors=vectors,
                chunks=[text_data],
                doc_id=new_app_id,
                provider_dir=str(provider_dir)
            )
            print(f"💾 Saved FAISS index for provider {new_app_id} (from license metadata).")
        else:
            print(f"⚠️ No structured provider data found to embed for {new_app_id}.")
    except Exception as e:
        print(f"❌ Failed to create FAISS for {new_app_id}: {e}")

    # --------------------------------------------------------
    # 🧾 Log and Save
    # --------------------------------------------------------
    record.setdefault("history", []).append({
        "event": "Application Accepted & Promoted",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"Promoted from {app_id} → {new_app_id} and created baseline FAISS."
    })

    save_all(apps)
    print(f"✅ Application {app_id} promoted → {new_app_id} and FAISS built successfully.")

    return RedirectResponse(url=f"/dashboard/view/{new_app_id}", status_code=303)



# ============================================================
# 🔴 3️⃣ Deny Application → Close It Out
# ============================================================
@router.post("/review/{app_id}/deny", response_class=HTMLResponse)
async def deny_application(request: Request, app_id: str, reason: str = Form(...)):
    """
    Deny an unfit application.
    Sets status → 'Denied' and logs reason.
    """
    apps = load_applications()
    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found for ID: {app_id}</h3>", status_code=404)

    record["status"] = "Denied"
    record.setdefault("history", []).append({
        "event": f"Application Denied ({reason})",
        "timestamp": datetime.utcnow().isoformat()
    })

    save_all(apps)
    print(f"❌ Application {app_id} denied. Reason: {reason}")

    return templates.TemplateResponse(
        "application_review.html",
        {
            "request": request,
            "application": record,
            "message": f"❌ Application denied: {reason}",
        },
    )
