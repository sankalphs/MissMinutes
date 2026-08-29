"""Ingest orchestrator — inventory -> Wyzie search -> SRT -> normalize -> store.

Usage:
  python scripts/ingest.py --pilot          # Avengers 2012 + Loki S01E01-02
  python scripts/ingest.py --movies         # all movies
  python scripts/ingest.py --series --slug loki_2021
  python scripts/ingest.py --all            # everything (respects daily budget)
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
from src.ingestion.wyzie import SubtitleHit, WyzieBudgetExceeded, WyzieClient  # noqa: E402

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


def ingest_target(
    client: WyzieClient,
    store: Store,
    entry: dict,
    season: int | None,
    episode: int | None,
) -> bool:
    document_id = doc_id_for(entry, season, episode)
    if store.has_document(document_id):
        log.info("skip (stored): %s", document_id)
        return True

    hits = client.search(entry["imdb_id"], season, episode)
    if not hits:
        # may be ledger-skip or genuinely no subs; check ledger explicitly
        target = entry["imdb_id"] if season is None else f"{entry['imdb_id']}/{season}/{episode}"
        if client.already_searched(target):
            log.info("skip (searched, no result stored): %s", target)
            return True
        log.warning("no hits: %s", target)
        return False
    hit = WyzieClient.pick_best(hits)

    raw_dir = settings.RAW_DIR / entry["timeline_id"]
    if season is None:
        raw_path = raw_dir / f"{entry['slug']}.srt"
    else:
        raw_path = raw_dir / f"{entry['slug']}_s{season:02d}e{episode:02d}.srt"

    try:
        client.download(hit, raw_path)
    except RuntimeError as e:
        log.error("download failed %s: %s", document_id, e)
        return False

    content = raw_path.read_text(encoding="utf-8", errors="replace")
    cues, chunks = normalize(content, document_id)
    if not chunks:
        log.warning("no chunks after normalize: %s", document_id)
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
            "source": hit.source,
            "release": hit.file_name,
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
    log.info("ingested %s: %d cues, %d chunks (%s)", document_id, len(cues), len(chunks), hit.file_name)
    return True


def run(targets: list[tuple[dict, int | None, int | None]], client: WyzieClient, store: Store) -> None:
    done = failed = 0
    for entry, s, e in targets:
        try:
            ok = ingest_target(client, store, entry, s, e)
        except WyzieBudgetExceeded as exc:
            log.error("BUDGET STOP: %s — resume tomorrow with same command", exc)
            break
        done += 1 if ok else 0
        failed += 0 if ok else 1
        time.sleep(1.0)
    log.info("run complete: %d ok, %d failed, budget spent today: %d", done, failed, client.spent_today())


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
            for s in entry.get("seasons", []):
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
    args = ap.parse_args()

    client = WyzieClient()
    store = Store()
    targets = build_targets(args)
    if args.movies:
        targets = [t for t in targets if t[0]["type"] == "movie"]
    if args.series:
        targets = [t for t in targets if t[0]["type"] == "series"]
    log.info("targets: %d (budget spent today: %d)", len(targets), client.spent_today())
    run(targets, client, store)
    log.info("store: %d docs, %d chunks", store.doc_count(), store.chunk_count())


if __name__ == "__main__":
    main()
