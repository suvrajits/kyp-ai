import os
import re
from pathlib import Path

# ----------- CONFIG -----------
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # adjust if needed
IGNORE_DIRS = {'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.mypy_cache'}
VALID_EXTENSIONS = {'.py', '.html', '.json', '.yaml', '.yml', '.txt', '.js'}
# ------------------------------

def get_all_files():
    """Return list of all candidate files in project."""
    files = []
    for root, dirs, filenames in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in filenames:
            if Path(f).suffix in VALID_EXTENSIONS:
                files.append(Path(root) / f)
    return files

def build_reference_index(files):
    """Build a big string corpus of all project files for searching."""
    index_text = ""
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                index_text += f.read().lower() + "\n"
        except Exception:
            pass
    return index_text

def find_unused_files(files, reference_text):
    """Return list of files not referenced anywhere."""
    unused = []
    for file in files:
        rel_path = str(file.relative_to(PROJECT_ROOT)).lower()
        name = file.stem.lower()

        # check if referenced by filename or path
        if name not in reference_text and rel_path not in reference_text:
            unused.append(rel_path)
    return unused

def main():
    print(f"🔍 Scanning project under: {PROJECT_ROOT}\n")
    all_files = get_all_files()
    print(f"Found {len(all_files)} files. Building index...")

    reference_text = build_reference_index(all_files)
    print("Index built. Checking references...")

    unused = find_unused_files(all_files, reference_text)
    print(f"\n🚫 Found {len(unused)} possibly unused files:\n")
    for f in unused:
        print(f" - {f}")

    # Save to report file
    report_path = PROJECT_ROOT / "unused_files_report.txt"
    with open(report_path, "w", encoding="utf-8") as out:
        out.write("\n".join(unused))
    print(f"\n📄 Report saved to {report_path}")

if __name__ == "__main__":
    main()
