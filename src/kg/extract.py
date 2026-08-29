"""KG extraction engine v2 — chunks -> GMI structured JSON -> pydantic gate -> cache.

Extraction (LLM) is separated from loading (graph writes in src/kg/load.py).
Every raw LLM response is cached in the `extractions` table keyed by
(chunk_id, model) so re-runs, model A/Bs, and loader changes never re-spend
API budget. Parallel via ThreadPoolExecutor; one worker = one HTTP call.
"""
import json
import logging
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from src.kg.schemas import ChunkExtraction
from src.llm.client import GMIError, GMIClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract a temporal knowledge graph from movie/TV subtitle dialogue
for Marvel-related screen canon (MCU, Sony Spider-verse, Fox X-Men, Netflix Defenders).
Output ONLY a JSON object, no prose, with keys:
"entities": [{"name": str, "type": "Character|Event|Location|Object|Organization",
              "aliases": [str]}],
"events": [{"name": str (short verb phrase, e.g. "Loki steals the Tesseract",
                         or the canonical name if the dialogue names it,
                         e.g. "Battle of New York", "the Snap"),
            "participants": [str], "objects": [str], "location": str|null,
            "date": str|null (year/date if the passage states one), "date_precision": "year|month|day|unknown",
            "evidence_quote": str (exact words from the passage)}],
"relations": [{"source": str, "relation": "PARTICIPATES_IN|USES|MEMBER_OF|OCCURS_AT|CAUSES|KNOWS|ENEMY_OF|ALLIED_WITH|FAMILY_OF|ROMANTIC_WITH",
               "target": str, "evidence_quote": str}],
"temporals": [{"event_a": str, "event_b": str,
                "relation": "BEFORE|AFTER|DURING|CAUSES", "evidence_quote": str}]
Rules:
- Only extract what the passage explicitly supports. evidence_quote MUST be
  verbatim words from the passage.
- Characters = named individuals; Organizations = groups (TVA, HYDRA, Avengers, SHIELD).
- Objects = physical items (Tesseract, Mjolnir). Locations = places.
- Use the character's best-known name (e.g. "Iron Man" not "the metal guy"),
  but keep quotes verbatim.
- Skip background noise (music cues, sound descriptions).
- Do NOT invent names not grounded in the passage.
- Empty lists are fine for keys with nothing to extract."""


def ensure_cache(db_path) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS extractions (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            raw TEXT,
            error TEXT,
            extracted_at TEXT,
            PRIMARY KEY (chunk_id, model)
        )"""
    )
    con.commit()
    con.close()


def cache_get(db_path, chunk_id: str, model: str) -> tuple[str, Any] | None:
    """Returns (status, raw_parsed_or_none): 'ok'|'fail'."""
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT status, raw FROM extractions WHERE chunk_id = ? AND model = ?",
        (chunk_id, model),
    ).fetchone()
    con.close()
    if not row:
        return None
    status, raw = row
    parsed = None
    if status == "ok" and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    return (status, parsed)


def cache_put(db_path, chunk_id: str, model: str, status: str, raw: str | None, error: str | None = None) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO extractions (chunk_id, model, status, raw, error, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(chunk_id, model) DO UPDATE SET
             status = excluded.status, raw = excluded.raw,
             error = excluded.error, extracted_at = excluded.extracted_at""",
        (chunk_id, model, status, raw, error, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def extract_chunk(llm: GMIClient, chunk_text: str, doc_title: str) -> tuple[ChunkExtraction | None, str | None]:
    """Returns (extraction_or_None, error_reason_or_None)."""
    user = (
        f'Passage from "{doc_title}":\n---\n{chunk_text}\n---\nExtract the knowledge graph.'
    )
    try:
        raw: Any = llm.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=3000,
        )
    except GMIError as e:
        return None, f"gmi:{str(e)[:120]}"
    if not isinstance(raw, dict):
        return None, "not_dict"
    try:
        return ChunkExtraction(**raw), None
    except ValidationError as e:
        return None, f"validation:{e.error_count()}"


def extract_one(llm: GMIClient, db_path, chunk: dict, model: str) -> tuple[str, ChunkExtraction | None]:
    """Extract one chunk with cache check. chunk = {chunk_id, text, title}.

    'ok' cache hits return instantly; 'fail' cache hits are retried
    (most failures are transient rate-limit/DNS noise).
    """
    cached = cache_get(db_path, chunk["chunk_id"], model)
    if cached:
        status, parsed = cached
        if status == "ok":
            try:
                return chunk["chunk_id"], ChunkExtraction(**parsed)
            except ValidationError:
                pass  # cached raw no longer valid for current schema — re-extract

    extraction, error = extract_chunk(llm, chunk["text"], chunk["title"])
    if extraction is None:
        cache_put(db_path, chunk["chunk_id"], model, "fail", None, error)
        return chunk["chunk_id"], None
    cache_put(db_path, chunk["chunk_id"], model, "ok", extraction.model_dump_json())
    return chunk["chunk_id"], extraction


def select_chunks(store_db, doc_prefix: str | None = None, only_missing_for: tuple = (),
                  window_chars: int = 2200) -> list[dict]:
    """Extraction windows: aggregate citation-granularity chunks into larger
    windows (~window_chars) for the LLM. Subtitle chunks are tiny (100-300
    chars); the LLM needs more context to extract events and relations.
    Window ids are stable: doc#w<N> where N counts windows in the doc.
    """
    con = sqlite3.connect(store_db)
    sql = (
        "SELECT c.chunk_id, c.document_id, c.text, d.title FROM chunks c "
        "JOIN documents d ON d.document_id = c.document_id"
    )
    params: list = []
    if doc_prefix:
        sql += " WHERE c.document_id LIKE ?"
        params.append(f"{doc_prefix}%")
    sql += " ORDER BY c.document_id, c.chunk_id"
    rows = con.execute(sql, params).fetchall()
    con.close()

    windows: list[dict] = []
    by_doc: dict[str, list] = defaultdict(list)  # doc_id -> [(chunk_id, text, title)]
    for chunk_id, document_id, text, title in rows:
        by_doc[document_id].append((chunk_id, text, title))

    for document_id, items in by_doc.items():
        title = items[0][2]
        doc_windows: list[dict] = []
        buf: list[str] = []      # member chunk_ids
        buf_text: list[str] = []
        for chunk_id, text, _ in items:
            if buf and len(" ".join(buf_text)) + len(text) > window_chars:
                doc_windows.append({
                    "chunk_id": f"{document_id}#w{len(doc_windows):04d}",
                    "document_id": document_id,
                    "text": " ".join(buf_text),
                    "title": title,
                    "member_chunks": list(buf),
                })
                buf, buf_text = [], []
            buf.append(chunk_id)
            buf_text.append(text)
        if buf:
            doc_windows.append({
                "chunk_id": f"{document_id}#w{len(doc_windows):04d}",
                "document_id": document_id,
                "text": " ".join(buf_text),
                "title": title,
                "member_chunks": list(buf),
            })
        windows.extend(doc_windows)
    if only_missing_for:
        have = set()
        con = sqlite3.connect(store_db)
        qmarks = ",".join("?" for _ in only_missing_for)
        for (cid,) in con.execute(
            f"SELECT chunk_id FROM extractions WHERE status = 'ok' AND model IN ({qmarks})",
            only_missing_for,
        ).fetchall():
            have.add(cid)
        con.close()
        windows = [w for w in windows if w["chunk_id"] not in have]
    return windows


def run_extraction(
    llm: GMIClient,
    db_path,
    chunks: list[dict],
    workers: int = 8,
    limit: int | None = None,
) -> dict[str, int]:
    """Parallel extraction; returns totals. Results are in the cache table —
    graph loading is a separate pass (src/kg/load.py)."""
    ensure_cache(db_path)
    if limit:
        chunks = chunks[:limit]
    totals = {"attempted": 0, "ok": 0, "failed": 0}
    if not chunks:
        return totals

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(extract_one, llm, db_path, c, llm.model): c for c in chunks
        }
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                chunk_id, extraction = fut.result()
            except Exception as e:
                logger.error("worker crash on %s: %s", c["chunk_id"], e)
                totals["failed"] += 1
                continue
            totals["attempted"] += 1
            if extraction is None:
                totals["failed"] += 1
            else:
                totals["ok"] += 1
            if totals["attempted"] % 50 == 0:
                logger.info(
                    "progress: %d/%d (ok=%d failed=%d)",
                    totals["attempted"], len(chunks), totals["ok"], totals["failed"],
                )
    return totals
