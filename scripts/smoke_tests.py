"""Phase 0C smoke tests — verify external APIs with minimal spend.

Run: python scripts/smoke_tests.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_gmi_json() -> None:
    from src.llm.client import GMIClient

    c = GMIClient()
    r = c.chat_json(
        [
            {
                "role": "system",
                "content": "You extract entities from subtitles. Output only JSON.",
            },
            {
                "role": "user",
                "content": (
                    'Extract entities as {"entities": [{"name": str, '
                    '"type": "Character|Object|Location|Organization"}]} from: '
                    '"Loki grabs the Tesseract and opens a portal above New York."'
                ),
            },
        ],
        temperature=0,
        max_tokens=300,
    )
    assert isinstance(r, dict) and "entities" in r, f"bad shape: {r}"
    names = [e["name"] for e in r["entities"]]
    print(f"  entities: {names}")
    assert any("Loki" in n for n in names), f"Loki missing: {r}"
    assert any("Tesseract" in n for n in names), f"Tesseract missing: {r}"


def test_wyzie() -> None:
    import time

    import httpx

    from src.config import settings

    for attempt in range(5):
        resp = httpx.get(
            f"{settings.WYZIE_BASE_URL}/search",
            params={
                "id": "tt0848228",  # The Avengers (2012)
                "language": "en",
                "format": "srt",
                "key": settings.WYZIE_API_KEY,
            },
            timeout=30,
        )
        if resp.status_code not in (429, 503):
            break
        time.sleep(3 * (attempt + 1))
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    if isinstance(data, list):
        assert len(data) > 0, "empty result"
        first = data[0]
    else:
        first = data
    print(f"  wyzie hit: {first.get('media')} / {first.get('language')} / {first.get('fileName')}")
    assert first.get("url"), "no subtitle URL returned"


if __name__ == "__main__":
    import httpx

    print("GMI JSON smoke:")
    test_gmi_json()
    print("Wyzie smoke:")
    try:
        test_wyzie()
    except AssertionError as e:
        msg = str(e)
        # only a service-side outage defers; a 401/400 is a real failure
        if any(f"HTTP {code}" in msg for code in (429, 502, 503, 504)):
            print(f"  wyzie outage (service-side) — DEFERRED: {msg[:200]}")
            print("ALL SMOKE TESTS RUN (wyzie deferred)")
        else:
            raise
    except httpx.HTTPError as e:
        print(f"  wyzie unreachable (network) — DEFERRED: {e}")
        print("ALL SMOKE TESTS RUN (wyzie deferred)")
    else:
        print("ALL SMOKE TESTS PASSED")
