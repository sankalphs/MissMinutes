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


def main() -> None:
    attempts = 0
    while True:
        try:
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
            attempts += 1
            print(f"attempt {attempts}: {r.status_code}", flush=True)
            if r.status_code == 200:
                SIGNAL.parent.mkdir(parents=True, exist_ok=True)
                SIGNAL.write_text("wyzie is back", encoding="utf-8")
                print("WYZIE IS BACK — signal file written")
                return
            if r.status_code == 401 or r.status_code == 403:
                print("key rejected — stopping watch")
                return
        except httpx.HTTPError as e:
            print(f"network error: {e}", flush=True)
        time.sleep(120)


if __name__ == "__main__":
    main()
