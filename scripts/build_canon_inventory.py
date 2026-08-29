"""Phase 1: Canon inventory — build + verify via IMDb suggestion API.

Verifies every imdb_id in inventory.json against IMDb's free suggestion
endpoint (no API key, no budget). Corrects IDs when a better match is found,
marks unverifiable ones imdb_id_verified=false.

Run: python scripts/build_canon_inventory.py
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import settings  # noqa: E402

INVENTORY = settings.CANON_DIR / "inventory.json"


def imdb_suggest(query: str) -> list[dict]:
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", query).strip("_")
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{slug}.json"
    r = httpx.get(url, timeout=20)
    r.raise_for_status()
    return r.json().get("d", [])


def find_imdb(entry: dict) -> tuple[str, bool]:
    """Return (imdb_id, verified). Match by title+year+type from suggestions."""
    q = f"{entry['title']} {entry['year']}"
    try:
        items = imdb_suggest(q)
    except Exception:
        time.sleep(2)
        try:
            items = imdb_suggest(entry["title"])
        except Exception:
            return entry.get("imdb_id", ""), False
    want_type = "movie" if entry["type"] == "movie" else ("tvSeries" if not entry.get("is_miniseries") else "tvSeries")
    year = entry["year"]
    candidates = [
        i for i in items
        if str(i.get("id", "")).startswith("tt")
        and i.get("y") in (year, year - 1, year + 1)
    ]
    exact = [i for i in candidates if i.get("qid") == want_type and i.get("y") == year]
    if exact:
        return exact[0]["id"], True
    if candidates:
        # year/type near-match: prefer same qid, else nearest year
        same_qid = [i for i in candidates if i.get("qid") == want_type]
        pick = (same_qid or candidates)[0]
        title_match = pick.get("l", "").lower().startswith(entry["title"].lower()[:12])
        return pick["id"], bool(title_match)
    return entry.get("imdb_id", ""), False


def main() -> None:
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    print(f"Verifying {len(inv)} titles against IMDb...")
    fixed, unverified = 0, []
    for e in inv:
        old = e.get("imdb_id", "")
        new, ok = find_imdb(e)
        if not ok:
            unverified.append(f"{e['slug']}: kept {old or 'NONE'}")
        if new and new != old:
            fixed += 1
            print(f"  FIX {e['slug']}: {old or 'NONE'} -> {new} (verified={ok})")
        e["imdb_id"] = new or old
        e["imdb_id_verified"] = ok
        time.sleep(0.3)
    INVENTORY.write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")
    total_eps = sum(sum(int(v) for v in e.get("episode_counts", {}).values()) for e in inv if e["type"] == "series")
    print(f"\nDone: {len(inv)} titles | {fixed} IDs corrected | {len(unverified)} unverified")
    for u in unverified:
        print(f"  UNVERIFIED {u}")
    print(f"Total episodes to ingest: {total_eps}")


if __name__ == "__main__":
    main()
