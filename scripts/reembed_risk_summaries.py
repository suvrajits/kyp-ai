# scripts/reembed_risk_summaries.py
"""
Re-embed patched risk summaries into FAISS so the notes become part of RAG search.

Usage:
  # Dry-run (show what would be re-embedded)
  python scripts/reembed_risk_summaries.py --dry-run

  # Actually re-embed
  python scripts/reembed_risk_summaries.py --apply

Notes:
 - This script will prefer to call `calculate_provider_risk(provider_id, internal=True)`
   if available (that function in your codebase already handles embedding risk summaries).
 - If not available, it falls back to `embed_texts()` + `save_faiss_index()` (same approach used elsewhere).
 - It will NOT call the fine-tuned risk model; it only embeds summaries already present in files.
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
import sys

BASE = Path.cwd()
APP_JSON = BASE / "app" / "data" / "applications.json"
RISK_DIR = BASE / "app" / "data" / "risk"

def load_apps():
    if not APP_JSON.exists():
        print(f"ERROR: {APP_JSON} not found.")
        sys.exit(1)
    with APP_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)

def build_risk_blob(rec_id, risk_obj):
    """
    Build a compact textual blob for embedding from a risk object.
    - include summary (if any), aggregated score, risk level
    - include each category name + note (or score as fallback)
    """
    parts = []
    summary = risk_obj.get("summary")
    if summary:
        parts.append(f"Summary: {summary}")

    agg = risk_obj.get("aggregated_score") or risk_obj.get("risk_score") or risk_obj.get("aggregatedScore")
    lvl = risk_obj.get("risk_level") or risk_obj.get("riskLevel")
    if agg is not None or lvl is not None:
        parts.append(f"Overall: {lvl or 'Unknown'} ({agg if agg is not None else 'N/A'}%)")

    cats = risk_obj.get("category_scores") or {}
    if isinstance(cats, dict) and cats:
        parts.append("Category details:")
        for cat, val in cats.items():
            if isinstance(val, dict):
                score = val.get("score", "N/A")
                note = val.get("note") or val.get("reason") or ""
                parts.append(f"- {cat}: {score}% — {note}")
            else:
                # flat numeric value
                parts.append(f"- {cat}: {val}% — No reasoning available")
    else:
        parts.append("No category breakdown available.")

    # join parts into final document
    return "\n".join(parts).strip()


def attempt_call_calculate_provider_risk():
    """
    Try to import calculate_provider_risk(provider_id, internal=True).
    Return function reference or None.
    """
    try:
        from app.routes.risk_router import calculate_provider_risk
        return calculate_provider_risk
    except Exception:
        return None

def fallback_embed_and_save(provider_id, text_blob):
    """
    Fallback embedding flow: embed_texts + save_faiss_index as used in the app routes.
    This requires app.rag.ingest.embed_texts and app.rag.vector_store_faiss.save_faiss_index.
    """
    try:
        from app.rag.ingest import embed_texts
        from app.rag.vector_store_faiss import save_faiss_index
    except Exception as e:
        raise RuntimeError("Fallback embedding modules not available: " + str(e))

    # create a one-element embedding and save to provider faiss folder
    vectors = embed_texts([text_blob])
    # Normalize if your pipeline otherwise does
    try:
        import faiss, numpy as np
        faiss.normalize_L2(vectors)
    except Exception:
        pass

    provider_dir = Path("app/data/faiss_store") / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    save_faiss_index(
        vectors=vectors,
        chunks=[text_blob],
        doc_id=f"risk_summary_{provider_id}",
        provider_dir=str(provider_dir)
    )
    return True


def main(dry_run=False, apply=False):
    apps = load_apps()
    print(f"📂 Loaded {len(apps)} application(s) from {APP_JSON}")

    calc_fn = attempt_call_calculate_provider_risk()
    if calc_fn:
        print("🔁 Found calculate_provider_risk() — will use it for embedding (safe, project-native).")
    else:
        print("ℹ️ calculate_provider_risk() not found — will use fallback embed_texts() + save_faiss_index()")

    candidates = []
    for rec in apps:
        rec_id = rec.get("id") or rec.get("application_id")
        risk = rec.get("risk")
        # also accept standalone risk files in RISK_DIR if applications.json lacks risk
        if not risk:
            # attempt to load file under app/data/risk/<id>.json
            f = RISK_DIR / f"{rec_id}.json"
            if f.exists():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    # allow both top-level or model_response shapes
                    if "model_response" in data:
                        risk = data["model_response"]
                    else:
                        risk = data
                except Exception:
                    continue

        if not risk:
            continue

        # build text blob
        blob = build_risk_blob(rec_id, risk)
        candidates.append((rec_id, blob))

    if not candidates:
        print("ℹ️ No risk summaries found to re-embed. Exiting.")
        return

    print(f"ℹ️ {len(candidates)} provider(s) will be considered for re-embedding.")
    for pid, blob in candidates:
        print(f" - {pid}: {len(blob.splitlines())} lines, {len(blob)} chars")

    if dry_run:
        print("\nDry-run complete. No embeddings were written.")
        return

    # apply mode: actually re-embed
    errors = []
    for pid, blob in candidates:
        print(f"\n🔁 Embedding risk summary for {pid}...")
        try:
            if calc_fn:
                # calculate_provider_risk(provider_id) in your project often triggers both embedding and indexing.
                # Use the 'internal=True' flag if available to avoid re-evaluation of the model.
                try:
                    # try with internal kwarg
                    res = calc_fn(pid, internal=True)
                    # If calculate_provider_risk is async or returns coroutine, await it
                    import inspect, asyncio
                    if inspect.isawaitable(res):
                        asyncio.get_event_loop().run_until_complete(res)
                except TypeError:
                    # function signature may differ; try calling without internal
                    res = calc_fn(pid)
                    if inspect.isawaitable(res):
                        asyncio.get_event_loop().run_until_complete(res)
            else:
                # fallback embedding
                fallback_embed_and_save(pid, blob)

            print(f"✅ Successfully (re)embedded risk summary for {pid}")
        except Exception as e:
            print(f"❌ Failed to embed for {pid}: {e}")
            errors.append((pid, str(e)))

    if errors:
        print("\n⚠️ Some embeddings failed:")
        for pid, err in errors:
            print(f" - {pid}: {err}")
    else:
        print("\n✅ All re-embeddings completed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview which providers will be re-embedded.")
    parser.add_argument("--apply", action="store_true", help="Actually perform embedding and save to FAISS.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, apply=args.apply)
