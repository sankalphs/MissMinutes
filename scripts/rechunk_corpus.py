"""Re-chunk the existing corpus with the current normalize rules (exp/chunking).

Reads raw SRTs from disk for every document in the source DB, re-runs
parse + normalize, and writes a fresh DB (documents copied verbatim,
chunks rebuilt) ready for scripts/index_vectors.py. Docs whose raw SRT
no longer exists on disk are skipped and counted — their chunks cannot
be rebuilt.

Run: python scripts/rechunk_corpus.py [--db ...] [--raw-dir ...] [--source-db ...]
"""
import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.normalize import normalize  # noqa: E402
from src.ingestion.store import Store  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("rechunk")


def _norm_name(s: str) -> str:
    """Mirror the download naming in SubtitlecatClient: release files are
    saved as <norm(title)>_<movie|sXXeYY>.srt, not always <slug>.srt."""
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip("_")


def find_raw(raw_files: dict[str, Path], doc: dict) -> Path | None:
    """Locate the raw SRT for a document; raw_files keys are lowercase names."""
    slug = doc["document_id"].removeprefix("doc:")
    tag = "movie" if doc["season"] is None else f"s{doc['season']:02d}e{doc['episode']:02d}"
    candidates = [f"{slug}.srt"]
    if doc["season"] is not None:
        candidates.append(f"{slug}_s{doc['season']:02d}e{doc['episode']:02d}.srt")
    candidates.append(f"{_norm_name(doc['title'])}_{tag}.srt")
    for c in candidates:
        hit = raw_files.get(c.lower())
        if hit:
            return hit
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("data/missminutes_c1.db"))
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw/subtitlecat"))
    ap.add_argument("--source-db", type=Path, default=Path("data/missminutes.db"))
    args = ap.parse_args()

    if args.db.exists():
        log.info("removing stale %s", args.db)
        args.db.unlink()

    src = sqlite3.connect(args.source_db)
    old_chunks, old_avg = src.execute(
        "SELECT COUNT(*), AVG(LENGTH(text)) FROM chunks"
    ).fetchone()

    store = Store(args.db)
    con = store.con
    # documents rows carry title/year/season/episode — copied verbatim so the
    # eval harness sees identical documents; chunk_count is updated per doc
    con.execute("ATTACH DATABASE ? AS source", (str(args.source_db.resolve()),))
    con.execute("INSERT OR REPLACE INTO documents SELECT * FROM source.documents")
    con.commit()
    con.execute("DETACH DATABASE source")

    raw_files = {p.name.lower(): p for p in args.raw_dir.glob("*.srt")}
    log.info("raw dir holds %d srt files", len(raw_files))

    no_raw_ids: list[str] = []
    processed = 0
    for doc in store.all_documents():
        raw = find_raw(raw_files, doc)
        if raw is None:
            no_raw_ids.append(doc["document_id"])
            log.warning("no raw srt, skipping: %s", doc["document_id"])
            continue
        content = raw.read_text(encoding="utf-8", errors="replace")
        _, chunks = normalize(content, doc["document_id"])
        store.replace_chunks(
            doc["document_id"],
            [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": doc["document_id"],
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
        con.execute(
            "UPDATE documents SET chunk_count = ? WHERE document_id = ?",
            (len(chunks), doc["document_id"]),
        )
        con.commit()
        processed += 1
    if no_raw_ids:
        con.executemany(
            "UPDATE documents SET chunk_count = 0 WHERE document_id = ?",
            [(d,) for d in no_raw_ids],
        )
        con.commit()

    new_chunks, new_avg = con.execute(
        "SELECT COUNT(*), AVG(LENGTH(text)) FROM chunks"
    ).fetchone()
    log.info(
        "rechunk complete: %d docs processed, %d skipped (no raw)",
        processed, len(no_raw_ids),
    )
    print(
        f"chunks: {new_chunks} (was {old_chunks}) | "
        f"avg chars: {new_avg:.1f} (was {old_avg:.1f})"
    )
    store.close()
    src.close()


if __name__ == "__main__":
    main()
