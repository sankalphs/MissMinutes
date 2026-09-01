"""Build the golden retrieval eval set (one-time, committed fixture).

Samples documents stratified across timelines, picks real subtitle chunks,
and asks the GMI model to write naturalistic fan questions whose answers
live in those chunks. Ground truth is stored as (document_id, chunk window)
— window-overlap matching keeps the fixture valid even if the corpus is
re-chunked. Hand additions carry the 3 benchmark questions with known docs.

Output: src/eval/fixtures/golden_retrieval.json

Usage:
  python scripts/build_golden_set.py            # full build (GMI credits)
  python scripts/build_golden_set.py --dry-run  # sample + windows only, no LLM
"""
import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

from src.config import settings
from src.db import connect
from src.ingestion.store import Store

FIXTURE = Path(__file__).resolve().parent.parent / "src" / "eval" / "fixtures" / "golden_retrieval.json"
CHECKPOINT = settings.PROCESSED_DIR / "golden_partial.json"

# docs sampled per timeline — proportionate but never zero for a branch
DOCS_PER_TIMELINE = {
    "defenders": 14, "mcu": 14, "whatif": 6, "fox:xmen": 5,
    "sony:ssu": 3, "sony:rami": 2, "sony:webb": 1,
}
CHUNK_MIN, CHUNK_MAX = 150, 800
SEED = 20260902

def build_prompt(a: str, b: str, title: str) -> str:
    """Interpolated per-call (never .format on user text — dialogue can
    contain braces)."""
    return f"""You write retrieval-test questions for a Marvel screen-canon search engine.

Below are TWO consecutive subtitle excerpts from ONE unseen movie/series.

EXCERPT A:
{a}

EXCERPT B:
{b}

Write three questions a curious Marvel fan might type into a search box:
- "q1": answerable from EXCERPT A specifically.
- "q2": answerable from EXCERPT A specifically, about a DIFFERENT fact than q1.
- "qdoc": only if this is the movie "{title}" — a question whose ANSWER is
  that movie's title (e.g. "Which movie shows ...?"). NEVER include the title
  itself, or any word of it, in the question. For a series/episode output null.

Rules for all questions: natural phrasing, 8-20 words, no 6+ consecutive
words copied from the excerpts, never name the movie/series.
Return ONLY JSON: {{"q1": str, "q2": str, "qdoc": str|null}}"""


def _verbatim_overlap(question: str, text: str, n: int = 6) -> bool:
    qw = re.findall(r"[a-z0-9']+", question.lower())
    tw = re.findall(r"[a-z0-9']+", text.lower())
    tw_join = " " + " ".join(tw) + " "
    for i in range(len(qw) - n + 1):
        if " " + " ".join(qw[i:i + n]) + " " in tw_join:
            return True
    return False


def select_documents(store: Store, rng: random.Random) -> list[dict]:
    by_tl: dict[str, list[dict]] = defaultdict(list)
    for d in store.all_documents():
        if (d.get("chunk_count") or 0) >= 30:
            by_tl[d["timeline_id"]].append(d)
    chosen: list[dict] = []
    for tl, n in DOCS_PER_TIMELINE.items():
        cands = by_tl.get(tl, [])
        chosen.extend(rng.sample(cands, min(n, len(cands))))
    return chosen


def pick_chunks(con, document_id: str, rng: random.Random) -> list[dict]:
    rows = con.execute(
        "SELECT chunk_id, text, start_ms, end_ms FROM chunks "
        "WHERE document_id = ? ORDER BY cue_start", (document_id,)
    ).fetchall()
    pool = [r for r in rows if CHUNK_MIN <= len(r[1]) <= CHUNK_MAX]
    if len(pool) < 2:
        pool = [r for r in rows if len(r[1]) >= 80]
    if not pool:
        return []
    rng.shuffle(pool)
    picked: list[dict] = []
    for r in pool:
        if all(abs(r[3] - p["end_ms"]) > 60_000 for p in picked):
            picked.append({"chunk_id": r[0], "text": r[1], "start_ms": r[2], "end_ms": r[3]})
        if len(picked) == 2:
            break
    return picked


def neighbor_windows(con, document_id: str, start_ms: int, end_ms: int) -> tuple[float, float, float, float]:
    """Golden window + ±1-chunk padded window (seconds), for adjacent-tolerant
    chunk matching after any future re-chunking."""
    prev = con.execute(
        "SELECT end_ms FROM chunks WHERE document_id = ? AND end_ms < ? "
        "ORDER BY end_ms DESC LIMIT 1", (document_id, start_ms),
    ).fetchone()
    nxt = con.execute(
        "SELECT end_ms FROM chunks WHERE document_id = ? AND start_ms > ? "
        "ORDER BY start_ms LIMIT 1", (document_id, end_ms),
    ).fetchone()
    return (
        start_ms / 1000.0, end_ms / 1000.0,
        (prev[0] if prev else start_ms) / 1000.0,
        (nxt[0] if nxt else end_ms) / 1000.0,
    )


def slug_lookup(con, slug: str) -> str | None:
    row = con.execute(
        "SELECT document_id FROM documents WHERE slug = ?", (slug,)
    ).fetchone()
    if row:
        return row[0]
    like = slug.replace("_", "%")
    row = con.execute(
        "SELECT document_id FROM documents WHERE slug LIKE ? LIMIT 1", (f"%{like}%",)
    ).fetchone()
    return row[0] if row else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rng = random.Random(SEED)
    store = Store()
    con = connect(store.path)

    docs = select_documents(store, rng)
    print(f"selected {len(docs)} docs across {len({d['timeline_id'] for d in docs})} timelines")

    cases: list[dict] = []
    done: set[str] = set()
    if CHECKPOINT.exists():
        partial = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        cases = partial["cases"]
        done = set(partial.get("done_docs", []))
        print(f"resuming: {len(done)} docs already generated")

    llm = None
    if not args.dry_run:
        from src.llm.client import GMIClient

        llm = GMIClient()

    for i, doc in enumerate(docs):
        if doc["document_id"] in done:
            continue
        chunks = pick_chunks(con, doc["document_id"], rng)
        if len(chunks) < 2:
            print(f"skip {doc['document_id']}: not enough usable chunks")
            continue
        a, b = chunks[0], chunks[1]

        if args.dry_run:
            qs = {"q1": f"[dry] question about {doc['document_id']} 1",
                  "q2": f"[dry] question about {doc['document_id']} 2", "qdoc": None}
        else:
            try:
                qs = llm.chat_json([
                    {"role": "system", "content": "Return ONLY the JSON requested."},
                    {"role": "user", "content": build_prompt(
                        a["text"][:1200], b["text"][:800], doc["title"])},
                ], temperature=0.4, max_tokens=400)
            except Exception as e:
                print(f"LLM failed for {doc['slug']}: {e} — retrying once")
                time.sleep(2)
                try:
                    qs = llm.chat_json([
                        {"role": "user", "content": build_prompt(
                            a["text"][:1200], b["text"][:800], doc["title"])},
                    ], temperature=0.2, max_tokens=400)
                except Exception as e2:
                    print(f"giving up on {doc['slug']}: {e2}")
                    continue

        for key, chunk in (("q1", a), ("q2", b)):
            q = (qs.get(key) or "").strip()
            if not q or _verbatim_overlap(q, chunk["text"]):
                print(f"  drop {doc['document_id']}.{key}: {'verbatim overlap' if q else 'empty'}")
                continue
            s, e, es, ee = neighbor_windows(con, doc["document_id"],
                                            chunk["start_ms"], chunk["end_ms"])
            cases.append({
                "id": f"{doc['document_id']}#{key}", "kind": "chunk", "q": q,
                "document_id": doc["document_id"], "chunk_id": chunk["chunk_id"],
                "window": [s, e], "ext_window": [es, ee],
                "timeline": doc["timeline_id"], "source": "gmi",
            })

        qdoc = (qs.get("qdoc") or "").strip() if isinstance(qs.get("qdoc"), str) else ""
        if qdoc and doc.get("type") == "movie" and not _verbatim_overlap(qdoc, a["text"]):
            cases.append({
                "id": f"{doc['document_id']}#qdoc", "kind": "doc", "q": qdoc,
                "document_id": doc["document_id"], "chunk_id": None,
                "window": None, "ext_window": None,
                "timeline": doc["timeline_id"], "source": "gmi",
            })

        done.add(doc["document_id"])
        CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT.write_text(json.dumps(
            {"done_docs": sorted(done), "cases": cases}, indent=1), encoding="utf-8")
        print(f"[{i + 1}/{len(docs)}] {doc['slug']} ok ({len(cases)} cases so far)")

    # benchmark questions with known golden docs, for cross-checking the
    # fixture against the repo's own benchmark expectations
    for bi, (slug, q) in enumerate((
        ("the_avengers_2012", "What happened after Loki escaped with the Tesseract?"),
        ("wanda_vision_2021", "Which timeline does WandaVision belong to?"),
        ("wanda_vision_2021", "How did Wanda create Westview?"),
    )):
        doc_id = slug_lookup(con, slug)
        if doc_id:
            cases.append({
                "id": f"bench:{bi}:{slug}", "kind": "chunk", "q": q,
                "document_id": doc_id, "chunk_id": None,
                "window": None, "ext_window": None,
                "timeline": "mcu", "source": "benchmark",
            })

    # questions must be unique — a duplicate judges the same query twice
    seen: set[str] = set()
    unique = []
    for c in cases:
        key = re.sub(r"\W+", "", c["q"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(c)

    fixture = {
        "meta": {
            "built": time.strftime("%Y-%m-%d"),
            "seed": SEED,
            "docs": store.doc_count(),
            "chunks": store.chunk_count(),
            "model": settings.GMI_MODEL if not args.dry_run else "dry-run",
        },
        "cases": unique,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    kinds = defaultdict(int)
    tls = defaultdict(int)
    for c in unique:
        kinds[c["kind"]] += 1
        tls[c["timeline"]] += 1
    print(f"wrote {FIXTURE} — {len(unique)} cases "
          f"({dict(kinds)}, timelines: {dict(tls)})")


if __name__ == "__main__":
    main()
