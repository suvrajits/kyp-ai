# app/routes/provider_dashboard.py

# === top of provider_dashboard_bk.py ===
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from datetime import datetime
import json, os

from app.services.application_store import (
    load_applications,
    save_all,
    upsert_application,
    find_application,
    append_message,
    update_status,
)
from app.routes.upload import generate_temp_id

# Optional RAG helpers
from app.rag.ingest import embed_texts
from app.rag.vector_store_faiss import save_faiss_index
import faiss, numpy as np

router = APIRouter(tags=["Dashboard"])
# === end header ===


BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
DATA_DIR = BASE_DIR / "app" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 🔍 Utility Functions
# ============================================================
def _create_faiss_for_provider(app_id: str, provider: dict):
    """Embed provider details into FAISS store (used post-approval)."""
    try:
        provider_dir = Path("app/data/faiss_store") / app_id
        provider_dir.mkdir(parents=True, exist_ok=True)

        text_summary = " ".join([f"{k}: {v}" for k, v in provider.items()])
        vectors = embed_texts([text_summary])
        faiss.normalize_L2(vectors)
        save_faiss_index(
            vectors, [text_summary],
            doc_id="provider_profile",
            provider_dir=str(provider_dir)
        )
        print(f"✅ FAISS profile embedded for {app_id}")
    except Exception as e:
        print(f"⚠️ FAISS embedding failed for {app_id}: {e}")


# ============================================================
# 🟢 CREATE / APPROVE APPLICATION
# ============================================================
@router.post("/create-application")
async def create_application(request: Request, provider_data: str = Form(...)):
    """
    Create or reuse a provider application.
    - Existing provider → "Previously Approved"
    - New provider → "Under Review"
    """
    try:
        provider = json.loads(provider_data)
    except Exception:
        provider = {}

    # ✅ Check duplicates
    apps = load_applications()
    existing = next(
        (
            r for r in apps
            if (r.get("provider", {}).get("license_number") == provider.get("license_number"))
        ),
        None,
    )

    if existing:
        app_id = existing.get("id") or existing.get("application_id")
        print(f"ℹ️ Found existing provider {app_id}")

        # Ensure FAISS is created if missing
        provider_dir = Path("app/data/faiss_store") / app_id
        if not list(provider_dir.glob("*.index")):
            _create_faiss_for_provider(app_id, existing.get("provider", {}))

        return templates.TemplateResponse(
            "provider_dashboard.html",
            {
                "request": request,
                "app_id": app_id,
                "provider": existing.get("provider", {}),
                "status": existing.get("status", "Application Accepted"),
                "documents": existing.get("documents", []),
                "messages": existing.get("messages", []),
                "history": existing.get("history", []),
                "message": "ℹ️ Provider already exists and was previously approved.",
            },
        )

    # 🆕 New Application
    temp_id = generate_temp_id()
    record = {
        "id": temp_id,
        "application_id": temp_id,
        "provider": provider,
        "status": "Under Review",
        "documents": [],
        "messages": [],
        "created_at": datetime.utcnow().isoformat(),
        "history": [{"event": "Created", "timestamp": datetime.utcnow().isoformat()}],
    }

    upsert_application(record)
    request.app.state.current_application = record

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": temp_id,
            "provider": provider,
            "status": "Under Review",
            "documents": [],
            "messages": [],
            "history": [{"event": "Created", "timestamp": datetime.utcnow().isoformat()}],
            "message": "✅ New provider application submitted for review.",
        },
    )


# ============================================================
# 📄 VIEW EXISTING APPLICATION
# ============================================================
@router.get("/view/{app_id}", response_class=HTMLResponse)
async def view_dashboard(request: Request, app_id: str):
    """Display provider details, documents, and history (handles both id & application_id)."""
    apps = load_applications()

    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None
    )
    if not record:
        return HTMLResponse(f"<h3>❌ No provider found for App ID: {app_id}</h3>", status_code=404)

    # Normalize IDs for consistency
    record["id"] = record.get("id") or record.get("application_id") or app_id
    record["application_id"] = record.get("application_id") or record["id"]

    # TEMP-ID apps always show “Under Review”
    display_status = record.get("status", "Under Review")
    if record["id"].startswith("TEMP-ID") and display_status == "Application Accepted":
        display_status = "Under Review"

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": record["id"],
            "provider": record.get("provider", {}),
            "documents": record.get("documents", []),
            "status": display_status,
            "messages": record.get("messages", []),
            "history": record.get("history", []),
            "message": "📄 Provider dashboard loaded successfully.",
        },
    )


# ============================================================
# ❌ REJECT APPLICATION
# ============================================================
# ============================================================
# 🧩 APPLICATION LIFECYCLE ACTIONS
# ============================================================

@router.post("/approve/{app_id}", response_class=HTMLResponse)
async def approve_application(request: Request, app_id: str):
    """Approve an application."""
    updated = update_status(app_id, "Approved", note="Application approved by reviewer.")
    if updated:
        append_message(app_id, "System", "✅ Application approved successfully.")
        msg = "✅ Provider approved successfully."
    else:
        msg = "⚠️ Could not find the application to approve."

    record = find_application(app_id)
    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": record.get("provider", {}) if record else {},
            "documents": record.get("documents", []) if record else [],
            "status": record.get("status", "Approved") if record else "Unknown",
            "messages": record.get("messages", []) if record else [],
            "history": record.get("history", []) if record else [],
            "message": msg,
        },
    )


@router.post("/reject/{app_id}", response_class=HTMLResponse)
async def reject_application(request: Request, app_id: str, reason: str = Form(...)):
    """Reject a provider application with a reason."""
    updated = update_status(app_id, "Rejected", note=reason)
    if updated:
        append_message(app_id, "Reviewer", f"❌ Application rejected. Reason: {reason}")
        msg = f"❌ Application rejected for reason: {reason}"
    else:
        msg = "⚠️ Could not find application to reject."

    record = find_application(app_id)
    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": record.get("provider", {}) if record else {},
            "documents": record.get("documents", []) if record else [],
            "status": record.get("status", "Rejected") if record else "Unknown",
            "messages": record.get("messages", []) if record else [],
            "history": record.get("history", []) if record else [],
            "message": msg,
        },
    )


@router.post("/request-info/{app_id}", response_class=HTMLResponse)
async def request_info(request: Request, app_id: str, note: str = Form(...)):
    """Request more details or clarification from the provider."""
    updated = update_status(app_id, "Info Requested", note=note)
    if updated:
        append_message(app_id, "Reviewer", f"🟡 Additional information requested: {note}")
        msg = "🟡 Provider has been asked for more details."
    else:
        msg = "⚠️ Could not find the application to update."

    record = find_application(app_id)
    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": record.get("provider", {}) if record else {},
            "documents": record.get("documents", []) if record else [],
            "status": record.get("status", "Info Requested") if record else "Unknown",
            "messages": record.get("messages", []) if record else [],
            "history": record.get("history", []) if record else [],
            "message": msg,
        },
    )



# ============================================================
# 🗑️ DELETE DOCUMENT
# ============================================================
@router.post("/delete-document")
async def delete_document(request: Request, app_id: str = Form(...), filename: str = Form(...)):
    """Delete a specific uploaded document and its FAISS vector file."""
    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None
    )
    if not record:
        return HTMLResponse(f"<h3>❌ No provider found for App ID: {app_id}</h3>", status_code=404)

    provider_dir = Path("app/data/faiss_store") / app_id
    deleted_any = False

    if provider_dir.exists():
        for fname in os.listdir(provider_dir):
            if filename.split(".")[0] in fname:
                try:
                    os.remove(provider_dir / fname)
                    deleted_any = True
                    print(f"🗑️ Deleted {fname}")
                except Exception as e:
                    print(f"⚠️ Error deleting {fname}: {e}")

    record["documents"] = [
        d for d in record.get("documents", []) if d["filename"] != filename
    ]
    save_all(apps)

    msg = (
        f"✅ Deleted document '{filename}' and its FAISS index."
        if deleted_any else f"⚠️ No FAISS files found for '{filename}'."
    )

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": app_id,
            "provider": record.get("provider", {}),
            "documents": record.get("documents", []),
            "status": record.get("status", "Under Review"),
            "messages": record.get("messages", []),
            "history": record.get("history", []),
            "message": msg,
        },
    )


# ============================================================
# 🧾 SHOW UPLOAD FORM
# ============================================================
@router.get("/upload-form", response_class=HTMLResponse)
async def upload_form(request: Request):
    """Display upload form + registry grid."""
    apps = load_applications()
    sorted_apps = sorted(apps, key=lambda x: x.get("created_at", ""), reverse=True)

    return templates.TemplateResponse(
        "upload_form.html",
        {"request": request, "providers": sorted_apps},
    )

@router.post("/reject/{app_id}")
async def reject_provider(request: Request, app_id: str, reason: str = Form(...)):
    """Reject a provider application, record the reason, and log to history."""
    from app.services.application_store import load_applications, save_all, append_message
    apps = load_applications()

    record = next((r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id), None)
    if not record:
        return HTMLResponse(f"<h3>❌ Application not found: {app_id}</h3>", status_code=404)

    record["status"] = "Rejected"
    record.setdefault("history", []).append({
        "event": f"Rejected: {reason}",
        "timestamp": datetime.utcnow().isoformat()
    })
    record.setdefault("messages", []).append({
        "from": "Reviewer",
        "text": f"Application rejected. Reason: {reason}",
        "timestamp": datetime.utcnow().isoformat()
    })

    save_all(apps)
    print(f"🔄 Status for {app_id} → Rejected")

    return templates.TemplateResponse(
        "provider_dashboard.html",
        {
            "request": request,
            "app_id": record["id"],
            "provider": record.get("provider", {}),
            "documents": record.get("documents", []),
            "messages": record.get("messages", []),
            "history": record.get("history", []),
            "status": record["status"],
            "message": f"❌ Application rejected successfully. Reason: {reason}",
        },
    )

# ============================================================
# 🔍 SMART NATURAL LANGUAGE SEARCH
# ============================================================
@router.get("/search", response_class=HTMLResponse)
async def dashboard_search(request: Request, q: str = ""):
    """
    Lightweight natural-language provider search.
    Supports queries like:
      - 'NABH hospitals in Delhi'
      - 'government clinics with less than 50 beds'
    """
    from app.services.application_store import load_applications
    import re

    apps = load_applications()
    query = (q or "").strip().lower()
    if not query:
        return templates.TemplateResponse(
            "upload_form.html",
            {"request": request, "providers": apps, "query": q},
        )

    def match_provider(provider_record: dict) -> bool:
        p = provider_record.get("provider", {}) or {}
        blob = " ".join(str(v).lower() for v in p.values())

        # --- Synonym normalization ---
        synonyms = {
            "bengaluru": "bangalore",
            "delhi ncr": "delhi",
            "nabh accredited": "accreditation_status nabh",
            "nabl accredited": "accreditation_status nabl",
            "hospital": "type_of_institution hospital",
            "clinic": "type_of_institution clinic",
            "government": "ownership_details government",
            "private": "ownership_details private",
        }
        for k, v in synonyms.items():
            query_norm = query.replace(k, v)
        else:
            query_norm = query

        # --- Keyword-based matching ---
        tokens = query_norm.split()
        if all(t in blob for t in tokens):
            return True

        # --- Numeric condition: '>50 beds' ---
        m = re.search(r"([><=]*)(\d+)\s*beds?", query_norm)
        if m:
            try:
                val = int(str(p.get("number_of_beds", "0")).split()[0])
                op, n = m.group(1), int(m.group(2))
                if (">" in op and val > n) or ("<" in op and val < n) or val == n:
                    return True
            except Exception:
                pass

        return False

    filtered = [p for p in apps if match_provider(p)]
    print(f"🔍 Dashboard search: '{query}' → {len(filtered)} results")

    return templates.TemplateResponse(
        "upload_form.html",
        {"request": request, "providers": filtered, "query": q},
    )

@router.get("/risk/calc/{provider_id}")
async def calculate_risk(provider_id: str):
    from app.services.application_store import load_applications
    apps = load_applications()
    record = next((r for r in apps if r["id"] == provider_id), None)
    if not record:
        return {"risk_score": 0, "level": "Unknown"}

    provider = record.get("provider", {})
    score = 0

    # Example: Penalize missing or negative fields
    if provider.get("infrastructure_standards_compliance", "").lower().find("no") != -1:
        score += 20
    if provider.get("biomedical_waste_management_authorization", "").lower() != "yes":
        score += 10
    if provider.get("accreditation_status", "").lower() in ["none", "pending"]:
        score += 30
    if provider.get("license_expiry_date"):
        from datetime import datetime
        expiry = datetime.strptime(provider["license_expiry_date"], "%Y-%m-%d")
        if expiry < datetime.utcnow():
            score += 40

    risk_score = min(100, score)
    if risk_score >= 60:
        level = "High"
    elif risk_score >= 30:
        level = "Moderate"
    else:
        level = "Low"


    return {"risk_score": risk_score, "level": level}

@router.get("/docs/{app_id}")
async def list_provider_docs(app_id: str):
    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None,
    )
    if not record:
        return []
    return record.get("documents", [])

@router.get("/status/{provider_id}")
async def dashboard_status(provider_id: str):
    apps = load_applications()
    rec = next(
        (r for r in apps if r.get("id") == provider_id or r.get("application_id") == provider_id),
        None,
    )

    if not rec:
        return JSONResponse({"error": "Provider not found"}, status_code=404)

    # Extract
    risk = rec.get("risk", {})
    score = rec.get("risk_score") or risk.get("aggregated_score")
    categories = risk.get("category_scores", {}) or {}

    # Determine risk level (backend is authoritative)
    level = rec.get("risk_level")
    if not level:
        if score is None:
            level = "Unknown"
        elif score >= 60:
            level = "High"
        elif score >= 30:
            level = "Moderate"
        else:
            level = "Low"

    status = rec.get("risk_status") or "Completed"

    # Persist unified representation (prevents UI inconsistencies)
    rec["risk"] = {
        "aggregated_score": score,
        "category_scores": categories
    }
    rec["risk_score"] = score
    rec["risk_level"] = level
    rec["risk_status"] = status

    save_all(apps)

    return JSONResponse(
        {
            "status": status,
            "score": score,
            "level": level,
            "categories": categories,
        }
    )


@router.post("/append-message")
async def append_message_api(payload: dict):
    """
    Appends a chat message to a provider's application record.
    Required so toggles and risk resubmit work for newly sent messages.
    """
    app_id = payload.get("app_id")
    message = payload.get("message")

    if not app_id or not message:
        raise HTTPException(status_code=400, detail="Missing app_id or message")

    apps = load_applications()
    record = next(
        (r for r in apps if r.get("id") == app_id or r.get("application_id") == app_id),
        None
    )

    if not record:
        raise HTTPException(status_code=404, detail="Application not found")

    # Ensure messages array
    record.setdefault("messages", [])

    # Append message (includes id, from, text, use_for_risk)
    record["messages"].append(message)

    save_all(apps)
    return {"status": "ok", "saved": message}
