"""Retry Wyzie pilot search until service recovers; exits on first 200.

Run in background: python scripts/wyzie_watch.py
Writes data/processed/wyzie_back.txt on recovery as a signal file.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.config import settings  # noqa: E402

SIGNAL = settings.PROCESSED_DIR / "wyzie_back.txt"


def check_status() -> bool:
    """Poll /api/status (free, not budget-metered). True when any node is up."""
    try:
        r = httpx.get("https://sub.wyzie.io/api/status", timeout=15)
        if r.status_code != 200:
            return False
        nodes = r.json()
        return any(n.get("status") == "operational" for n in nodes.values())
    except Exception:
        return False


def main() -> None:
    attempts = 0
    while True:
        attempts += 1
        up = check_status()
        print(f"attempt {attempts}: {'UP' if up else 'degraded'}", flush=True)
        if up:
            # confirm with a real (budgeted) search
            r = httpx.get(
                "https://sub.wyzie.io/search",
                params={
                    "id": "tt0848228",
                    "language": "en",
                    "format": "srt",
                    "key": settings.WYZIE_API_KEY,
                },
                timeout=30,
            )
            print(f"confirm search: {r.status_code}", flush=True)
            if r.status_code == 200:
                SIGNAL.parent.mkdir(parents=True, exist_ok=True)
                SIGNAL.write_text("wyzie is back", encoding="utf-8")
                print("WYZIE IS BACK — signal file written")
                return
        time.sleep(120)


if __name__ == "__main__":
    main()
