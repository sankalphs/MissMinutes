"""Deploy MissMinutes to HF Space (requires HF PRO for gradio sdk).

Run: python scripts/deploy_space.py
Copies app.py, src/, space/README.md (as Space README), requirements.txt
into a temp dir and pushes to sankalphs/MissMinutes.
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

    # space README carries sdk metadata
    shutil.copy2(ROOT / "space" / "README.md", dst / "README.md")

    git = ["git", "-C", str(dst)]
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-m", "deploy missminutes"], check=True)
    subprocess.run(git + ["push"], check=True)
    print(f"Deployed to https://huggingface.co/spaces/{SPACE_ID}")


if __name__ == "__main__":
    sys.exit(main())
