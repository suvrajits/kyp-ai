# scripts/patch_risk_records.py
"""
Patch existing application records so that `risk.category_scores`
always stores objects { "score": <num>, "note": <str> } instead of raw numbers.

Usage:
  # dry-run (show what would change, don't write)
  python scripts/patch_risk_records.py --dry-run

  # actual run (creates backups, modifies data files)
  python scripts/patch_risk_records.py --apply

Notes:
 - Creates backups:
     app/data/applications.json.bak.<timestamp>
     app/data/risk/*.json.bak.<timestamp> (only for files modified)
 - Idempotent: running again will not change already-patched records.
 - Safe: if anything looks wrong, restore the .bak file.
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
from shutil import copy2
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

def save_apps(apps, backup_path):
    copy2(APP_JSON, backup_path)
    with APP_JSON.open("w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)
    print(f"✅ Wrote patched applications to {APP_JSON} (backup at {backup_path})")

def patch_category_scores(cat_scores):
    """
    Accepts category_scores (dict). If values are numbers, converts to
    {score: <n>, note: <placeholder>}. If already objects, leaves unchanged.
    Returns (patched_dict, changed_flag).
    """
    changed = False
    patched = {}
    for k, v in (cat_scores or {}).items():
        if isinstance(v, (int, float)):
            patched[k] = {
                "score": v,
                "note": "Imported from original application; reasoning not recorded."
            }
            changed = True
        elif isinstance(v, dict):
            # Ensure it has at least score and note keys (normalize)
            s = v.get("score")
            n = v.get("note") or v.get("reason") or "No reasoning available"
            # If score is nested as 'value' or similar, attempt to normalize
            if s is None and "value" in v and isinstance(v["value"], (int, float)):
                s = v["value"]
            patched[k] = {"score": s if s is not None else 0, "note": n}
            # If original dict didn't have 'note', we will mark changed to rewrite normalized form
            if "note" not in v or "score" not in v:
                changed = True
        else:
            # Unknown type — convert to default
            patched[k] = {"score": 0, "note": f"Unrecognized original value: {repr(v)}"}
            changed = True
    return patched, changed

def patch_risk_file(file_path, dry_run=False):
    """
    Patch app/data/risk/<id>.json if present and category_scores are flat.
    Returns True if file changed (or would change in dry-run).
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ Could not read {file_path}: {e}")
        return False

    # risk might be under data["model_response"] or data["model_response"] directly
    # Accept several shapes commonly used in the project
    root = data
    if "model_response" in data:
        root = data["model_response"]

    cat_scores = root.get("category_scores", {})
    if not cat_scores:
        return False

    patched, changed = patch_category_scores(cat_scores)
    if not changed:
        return False

    # apply patched structure
    root["category_scores"] = patched

    if dry_run:
        print(f"[DRY] Would patch risk file: {file_path}")
        return True

    # backup original file
    bak = file_path.with_suffix(file_path.suffix + f".bak.{TIMESTAMP}")
    copy2(file_path, bak)
    file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Patched risk file: {file_path} (backup: {bak})")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Patch old risk records to include reasoning placeholders.")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes; show what would change.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (create backups and overwrite files).")
    parser.add_argument("--patch-risk-files", action="store_true", help="Also patch files under app/data/risk/*.json (recommended).")
    args = parser.parse_args()

    TIMESTAMP = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    apps = load_apps()
    any_changes = False
    patched_count = 0

    print(f"📂 Loaded {len(apps)} application(s) from {APP_JSON}")

    for rec in apps:
        rec_id = rec.get("id") or rec.get("application_id") or "<unknown>"
        risk = rec.get("risk")
        if not risk:
            # nothing to do
            continue

        cat_scores = risk.get("category_scores", {})
        if not cat_scores:
            continue

        patched, changed = patch_category_scores(cat_scores)
        if changed:
            any_changes = True
            patched_count += 1
            print(f"{'[DRY] ' if args.dry_run else ''}Patching app {rec_id}: converting {len(cat_scores)} categories to object form.")
            # update in-memory record
            rec["risk"]["category_scores"] = patched
            # also normalize risk_score and risk_level presence
            if "aggregated_score" in rec["risk"] and not rec.get("risk_score"):
                rec["risk_score"] = rec["risk"]["aggregated_score"]
            if "risk_level" in rec["risk"] and not rec.get("risk_level"):
                rec["risk_level"] = rec["risk"]["risk_level"]

            # optionally patch the standalone risk file too
            if args.patch_risk_files:
                risk_file = RISK_DIR / f"{rec_id}.json"
                if risk_file.exists():
                    patch_risk_file(risk_file, dry_run=args.dry_run)

    if not any_changes:
        print("✅ No records required patching.")
        sys.exit(0)

    print(f"\nSummary: {patched_count} application record(s) would be/ were patched.")

    if args.dry_run:
        print("Dry-run complete. No files were modified.")
        sys.exit(0)

    if args.apply:
        # create backup of applications.json and write patched apps
        bak_app = APP_JSON.with_suffix(APP_JSON.suffix + f".bak.{TIMESTAMP}")
        save_apps(apps, bak_app)
        # optionally patch any orphan risk files not already patched
        if args.patch_risk_files:
            # scan risk dir for files matching app ids we patched
            for rec in apps:
                rec_id = rec.get("id") or rec.get("application_id")
                if not rec_id:
                    continue
                risk_file = RISK_DIR / f"{rec_id}.json"
                if risk_file.exists():
                    # ensure patched form (idempotent)
                    patch_risk_file(risk_file, dry_run=False)
        print("✅ Apply complete. If you need to revert, restore the .bak file for applications.json and any risk file backups.")
        sys.exit(0)
    else:
        print("No --apply flag provided; exiting without writing. Use --apply to persist changes.")
        sys.exit(0)
