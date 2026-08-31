"""Deploy MissMinutes to HF Space (requires HF PRO for gradio sdk).

Run: python scripts/deploy_space.py
Copies app.py, src/, ui/, space/README.md (as Space README), requirements.txt
and the SQLite corpus (data/missminutes.db — HF's git auto-LFSes >10MB
files) into a temp dir and pushes to sankalphs/MissMinutes.

The Qdrant store is NOT shipped (local-mode is single-process + ~360MB) —
the Space must set QDRANT_URL/QDRANT_API_KEY to a cloud collection
populated by scripts/index_vectors.py.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPACE_ID = "sankalphs/MissMinutes"


def main() -> None:
    tmp = Path.cwd() / "data" / "processed" / "space_staging"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    # clone space repo (empty ok)
    url = f"https://huggingface.co/spaces/{SPACE_ID}"
    subprocess.run(["git", "clone", url, str(tmp / "space")], check=True)

    dst = tmp / "space"
    for item in ["app.py", "requirements.txt", "pytest.ini", "src", "ui"]:
        src = ROOT / item
        if src.is_file():
            shutil.copy2(src, dst / item)
        else:
            shutil.copytree(src, dst / item, dirs_exist_ok=True)

    # the corpus: the Space's Store reads data/missminutes.db relative to
    # the repo root — without it the Space searches an empty archive
    db = ROOT / "data" / "missminutes.db"
    if db.exists():
        (dst / "data").mkdir(exist_ok=True)
        shutil.copy2(db, dst / "data" / "missminutes.db")
    else:
        print("WARNING: data/missminutes.db not found — the Space will run "
              "on an empty archive")

    # space README carries sdk metadata
    shutil.copy2(ROOT / "space" / "README.md", dst / "README.md")

    git = ["git", "-C", str(dst)]
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-m", "deploy missminutes"], check=True)
    subprocess.run(git + ["push"], check=True)
    print(f"Deployed to https://huggingface.co/spaces/{SPACE_ID}")


if __name__ == "__main__":
    sys.exit(main())
