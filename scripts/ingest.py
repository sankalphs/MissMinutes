"""Ingest orchestrator — inventory -> subtitle search -> SRT -> normalize -> store.

Usage:
  python scripts/ingest.py --pilot          # Avengers 2012 + Loki S01E01-02
  python scripts/ingest.py --movies         # all movies
  python scripts/ingest.py --series --slug loki_2021
  python scripts/ingest.py --all            # everything (resume-safe)
"""
import argparse
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.normalize import normalize  # noqa: E402
from src.ingestion.store import Store  # noqa: E402
from src.ingestion.subtitlecat import SubtitlecatClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ingest")


def load_inventory() -> list[dict]:
    import json

    return json.loads((settings.CANON_DIR / "inventory.json").read_text(encoding="utf-8"))


def doc_id_for(entry: dict, season: int | None, episode: int | None) -> str:
    base = entry["slug"]
    if season is None:
        return f"doc:{base}"
    return f"doc:{base}_s{season:02d}e{episode:02d}"


SPAM_MARKERS = [
    "mcephie", "moviesnipipay", "netnaija", "stagatv", "tagalog",
    "full4movies", "mkvcage", "kisscartoon",
]


def looks_like_wrong_content(doc_text: str, entry: dict) -> bool:
    """Guard against spam/watermark subtitle files only.

    Title-word heuristics are unreliable: movie titles like 'Quantumania' or
    'Wakanda Forever' are never spoken in dialogue. Release-name matching in
    the provider is already strict (exact episode markers, year, title phrase),
    so here we only block known spam watermarks.
    """
    text = doc_text.lower()
    return any(m in text for m in SPAM_MARKERS)


def ingest_target(
    client: SubtitlecatClient,
    store: Store,
    entry: dict,
    season: int | None,
    episode: int | None,
) -> bool:
    document_id = doc_id_for(entry, season, episode)
    if store.has_document(document_id):
        log.debug("skip (stored): %s", document_id)
        return True

    found = client.find_english_srt(entry["title"], entry["year"], season, episode)
    if not found:
        log.warning("no english srt found: %s", document_id)
        return False
    raw_path, release = found

    content = raw_path.read_text(encoding="utf-8", errors="replace")
    cues, chunks = normalize(content, document_id)
    if not chunks:
        log.warning("no chunks after normalize: %s", document_id)
        return False
    full_text = " ".join(c.text for c in cues)
    if looks_like_wrong_content(full_text, entry):
        log.error("WRONG CONTENT guard tripped: %s (release %s) — purge & skip", document_id, release[:60])
        raw_path.unlink(missing_ok=True)
        client.invalidate(entry["title"], entry["year"], season, episode)
        return False

    store.upsert_document(
        {
            "document_id": document_id,
            "slug": entry["slug"],
            "title": entry["title"],
            "year": entry["year"],
            "type": entry["type"],
            "timeline_id": entry["timeline_id"],
            "canonical": int(bool(entry.get("canonical", True))),
            "animated": int(bool(entry.get("animated", False))),
            "season": season,
            "episode": episode,
            "imdb_id": entry["imdb_id"],
            "source": "subtitlecat",
            "release": release,
            "cue_count": len(cues),
            "chunk_count": len(chunks),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store.replace_chunks(
        document_id,
        [
            {
                "chunk_id": c.chunk_id,
                "document_id": document_id,
                "scene_i": int(c.chunk_id.split("#s")[1][:4]),
                "cue_start": c.cue_start,
                "cue_end": c.cue_end,
                "start_ms": int(c.start_s * 1000),
                "end_ms": int(c.end_s * 1000),
                "text": c.text,
            }
            for c in chunks
        ],
    )
    log.info("ingested %s: %d cues, %d chunks (%s)", document_id, len(cues), len(chunks), release[:60])
    return True


def run(targets: list[tuple[dict, int | None, int | None]], client: SubtitlecatClient, store: Store,
        refresh_miss: bool = False) -> None:
    if refresh_miss:
        import sqlite3

        con = sqlite3.connect(store.path)
        n = con.execute("DELETE FROM source_cache WHERE status = 'miss'").rowcount
        con.commit()
        con.close()
        log.info("refreshed %d cached misses", n)
    done = failed = 0
    for entry, s, e in targets:
        try:
            ok = ingest_target(client, store, entry, s, e)
        except Exception as exc:
            log.error("target error %s: %s", entry["slug"], exc)
            ok = False
        done += 1 if ok else 0
        failed += 0 if ok else 1
        time.sleep(0.5)
    log.info("run complete: %d ok, %d failed", done, failed)


def build_targets(args: argparse.Namespace) -> list[tuple[dict, int | None, int | None]]:
    inv = load_inventory()
    targets: list[tuple[dict, int | None, int | None]] = []
    for entry in inv:
        if args.slug and entry["slug"] != args.slug:
            continue
        if args.animated is False and entry.get("animated"):
            continue
        if entry["type"] == "movie":
            targets.append((entry, None, None))
        else:
            for s in entry.get("seasons") or []:
                for e in range(1, int(entry["episode_counts"][str(s)]) + 1):
                    targets.append((entry, s, e))
    if args.pilot:
        targets = [
            t for t in targets
            if t[0]["slug"] == "the_avengers_2012"
            or (t[0]["slug"] == "loki_2021" and t[1] == 1 and t[2] in (1, 2))
        ]
    return targets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--movies", action="store_true")
    ap.add_argument("--series", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--slug", type=str, default=None)
    ap.add_argument("--no-animated", dest="animated", action="store_false")
    ap.add_argument("--refresh-miss", action="store_true", help="retry cached subtitle misses")
    args = ap.parse_args()

    if not (args.pilot or args.movies or args.series or args.all):
        ap.error("choose one of --pilot / --movies / --series / --all")

    store = Store()
    client = SubtitlecatClient()
    targets = build_targets(args)
    if args.movies:
        targets = [t for t in targets if t[0]["type"] == "movie"]
    if args.series:
        targets = [t for t in targets if t[0]["type"] == "series"]
    log.info("targets: %d", len(targets))
    run(targets, client, store, refresh_miss=args.refresh_miss)
    log.info("store: %d docs, %d chunks", store.doc_count(), store.chunk_count())


if __name__ == "__main__":
    main()
