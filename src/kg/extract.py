"""KG extraction engine — chunks -> GMI structured JSON -> validated -> graph.

spec:7,8,9,10 — one LLM call per chunk produces entities, events, relations,
temporals. Pydantic validation gates everything (spec:11). Validated facts
are written to Aura with provenance (chunk_id = evidence pointer, spec:5).
"""
import json
import logging
from typing import Any

from pydantic import ValidationError

from src.graph.schema import Graph
from src.ingestion.store import Store
from src.kg.resolve import EntityResolver
from src.kg.schemas import ChunkExtraction, ExtractedEntity, ExtractedEvent
from src.llm.client import GMIError, GMIClient
from src.vector.qdrant import chunk_point_id

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract a temporal knowledge graph from movie/TV subtitle text
for Marvel-related screen canon. Output ONLY a JSON object, no prose, with keys:
"entities": [{"name": str, "type": "Character|Event|Location|Object|Organization",
              "aliases": [str]}],
"events": [{"name": str (event title, e.g. "Loki steals the Tesseract"),
            "participants": [str], "objects": [str], "location": str|null,
            "date": str|null (mentioned year/date), "date_precision": "year|month|day|unknown",
            "evidence_quote": str (exact words from the passage)}],
"relations": [{"source": str, "relation": "PARTICIPATES_IN|USES|MEMBER_OF|OCCURS_AT|INVOLVES",
               "target": str, "evidence_quote": str}],
"temporals": [{"event_a": str, "event_b": str,
               "relation": "BEFORE|AFTER|DURING|CAUSES", "evidence_quote": str}]
Rules:
- Only extract what the passage explicitly supports. evidence_quote MUST be
  verbatim from the passage.
- Characters = named individuals; Organizations = groups (TVA, HYDRA, Avengers).
- Objects = physical items (Tesseract, Mjolnir). Locations = places.
- Do NOT invent names not grounded in the passage.
- Empty lists are fine for keys with nothing to extract."""


def extract_chunk(llm: GMIClient, chunk_text: str, doc_title: str) -> ChunkExtraction | None:
    user = (
        f"Passage from \"{doc_title}\":\n---\n{chunk_text}\n---\nExtract the knowledge graph."
    )
    try:
        raw: Any = llm.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=4000,
        )
    except GMIError as e:
        logger.warning("extraction failed for chunk: %s", e)
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return ChunkExtraction(**raw)
    except ValidationError as e:
        logger.warning("validation rejected extraction: %s", e.error_count())
        return None


def load_extraction(
    graph: Graph,
    resolver: EntityResolver,
    extraction: ChunkExtraction,
    doc: dict,
    chunk_id: str,
) -> dict[str, int]:
    """Write one validated extraction to Aura + resolver. Returns counts."""
    prov = {
        "chunk_id": chunk_id,
        "document_id": doc["document_id"],
        "source": doc.get("title"),
        "source_type": doc.get("type"),
        "timeline_id": doc.get("timeline_id"),
    }
    counts = {"entities": 0, "events": 0, "relations": 0, "temporals": 0}

    # entities
    for ent in extraction.entities:
        cid = resolver.register(ent.name, ent.type.value, ent.aliases)
        graph.merge_entity(
            {"id": cid, "name": ent.name, "type": ent.type.value},
            {"aliases": ent.aliases, **prov},
        )
        counts["entities"] += 1

    # events (Event nodes + PARTICIPATES_IN / INVOLVES / OCCURS_AT)
    for ev in extraction.events:
        ev_id = resolver.register(ev.name, "Event")
        graph.merge_entity(
            {"id": ev_id, "name": ev.name, "type": "Event"},
            {
                "date": ev.date,
                "date_precision": ev.date_precision,
                "location": ev.location,
                "evidence_quote": ev.evidence_quote,
                **prov,
            },
        )
        graph.merge_rel(ev_id, "OCCURS_IN", f"timeline:{doc.get('timeline_id')}", {"provenance": json.dumps(prov)})
        counts["events"] += 1
        for p in ev.participants:
            p_id = resolver.register(p, "Character")
            graph.merge_rel(p_id, "PARTICIPATES_IN", ev_id, {"provenance": json.dumps(prov)})
        for o in ev.objects:
            o_id = resolver.register(o, "Object")
            graph.merge_rel(ev_id, "INVOLVES", o_id, {"provenance": json.dumps(prov)})
        if ev.location:
            loc_id = resolver.register(ev.location, "Location")
            graph.merge_rel(ev_id, "OCCURS_AT", loc_id, {"provenance": json.dumps(prov)})

    # relations between named entities
    for rel in extraction.relations:
        src_id = resolver.resolve(rel.source, "Character")
        dst_id = resolver.resolve(rel.target, "Character")
        graph.merge_rel(src_id, rel.relation.value, dst_id, {"provenance": json.dumps(prov)})
        counts["relations"] += 1

    # temporal edges between events
    for t in extraction.temporals:
        a_id = resolver.resolve(t.event_a, "Event")
        b_id = resolver.resolve(t.event_b, "Event")
        # canonical direction: store BEFORE edges only
        if t.relation == "AFTER":
            a_id, b_id = b_id, a_id
        graph.merge_rel(a_id, t.relation if t.relation != "AFTER" else "BEFORE", b_id,
                        {"provenance": json.dumps(prov)})
        counts["temporals"] += 1

    return counts


def run_extraction(store: Store, llm: GMIClient, limit: int | None = None,
                   doc_prefix: str | None = None) -> dict[str, int]:
    """Extract KG from all chunks (optionally filtered). Resume-safe via
    extraction_ledger table."""
    import sqlite3
    from datetime import datetime, timezone

    con = sqlite3.connect(store.path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS extraction_ledger (
            chunk_id TEXT PRIMARY KEY,
            extracted_at TEXT,
            ok INTEGER
        )"""
    )
    con.commit()

    sql = (
        "SELECT c.chunk_id, c.document_id, c.text, d.title, d.timeline_id, d.type "
        "FROM chunks c JOIN documents d ON d.document_id = c.document_id"
    )
    params: list = []
    if doc_prefix:
        sql += " WHERE c.document_id LIKE ?"
        params.append(f"{doc_prefix}%")
    rows = con.execute(sql, params).fetchall()
    con.close()

    graph = Graph()
    resolver = EntityResolver()
    totals = {"entities": 0, "events": 0, "relations": 0, "temporals": 0, "chunks": 0, "failed": 0}
    for chunk_id, document_id, text, title, timeline_id, dtype in rows:
        con = sqlite3.connect(store.path)
        done = con.execute(
            "SELECT ok FROM extraction_ledger WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        con.close()
        if done:
            continue
        extraction = extract_chunk(llm, text, title)
        if extraction is None:
            totals["failed"] += 1
            con = sqlite3.connect(store.path)
            con.execute("INSERT OR REPLACE INTO extraction_ledger VALUES (?, ?, 0)",
                        (chunk_id, datetime.now(timezone.utc).isoformat()))
            con.commit()
            con.close()
            continue
        doc = {"document_id": document_id, "title": title,
               "timeline_id": timeline_id, "type": dtype}
        counts = load_extraction(graph, resolver, extraction, doc, chunk_id)
        for k in ("entities", "events", "relations", "temporals"):
            totals[k] += counts[k]
        totals["chunks"] += 1
        con = sqlite3.connect(store.path)
        con.execute("INSERT OR REPLACE INTO extraction_ledger VALUES (?, ?, 1)",
                    (chunk_id, datetime.now(timezone.utc).isoformat()))
        con.commit()
        con.close()
        if limit and totals["chunks"] >= limit:
            break
    graph.close()
    return totals
