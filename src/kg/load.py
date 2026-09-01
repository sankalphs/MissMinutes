"""KG loader v2 — cached extractions -> Neo4j Aura, batched UNWIND writes.

Reads validated extractions from the `extractions` cache table and writes
entities, events, relations, temporals with provenance. Batches of ~500
rows per UNWIND instead of one session per node (the v1 bottleneck).
Creates Movie/Series/Episode nodes and DEPICTED_IN / APPEARS_IN edges so
timeline queries can walk the graph, not just FTS.
"""
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from src.graph.schema import NODE_LABELS, Graph
from src.ingestion.store import Store
from src.kg.resolve import EntityResolver
from src.kg.schemas import ChunkExtraction

logger = logging.getLogger(__name__)

BATCH = 500


def _rows(db_path, model: str) -> list[tuple]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT chunk_id, raw FROM extractions WHERE status = 'ok' AND model = ?",
        (model,),
    ).fetchall()
    con.close()
    return rows


def load_all(graph: Graph, resolver: EntityResolver, store: Store, model: str,
             doc_prefix: str | None = None, resume: bool = True) -> dict[str, int]:
    """Load every cached extraction for `model` into the graph.

    Resume-safe: the `load_ledger` table records loaded window ids; with
    resume=True only unloaded windows are processed (MERGE keeps re-runs
    idempotent but skipping is far faster).
    """
    con = sqlite3.connect(store.path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS load_ledger (
            chunk_id TEXT NOT NULL,
            model TEXT NOT NULL,
            loaded_at TEXT,
            PRIMARY KEY (chunk_id, model)
        )"""
    )
    con.commit()
    if resume:
        loaded = {
            r[0] for r in con.execute(
                "SELECT chunk_id FROM load_ledger WHERE model = ?", (model,)
            ).fetchall()
        }
    else:
        loaded = set()
        con.execute("DELETE FROM load_ledger WHERE model = ?", (model,))
        con.commit()
    con.close()

    totals = {"nodes": 0, "entities": 0, "events": 0, "relations": 0,
              "temporals": 0, "chunks": 0, "skipped": 0}
    docs = store.all_documents()
    doc_by_id = {d["document_id"]: d for d in docs}

    # document nodes first (Movie / Series / Episode labels)
    _load_documents(graph, docs, doc_prefix)

    rows = [r for r in _rows(store.path, model) if r[0] not in loaded]
    logger.info("loading %d cached extractions (model=%s, %d already loaded)",
                len(rows), model, len(loaded))

    # node rows keyed by id: every registered endpoint becomes a node write,
    # otherwise MATCH in _write_rels silently drops the edge (dangling end)
    ent_batch: dict[str, dict] = {}
    ev_batch: list[dict] = []
    rel_batch: list[dict] = []
    ledger_batch: list[tuple] = []

    def queue_entity(cid: str, prov: str, chunk: str) -> None:
        """Queue a node write for a registered id, using the resolver's
        canonical name/type. Richest alias set wins across chunks."""
        ent = resolver.entity(cid)
        if ent is None:
            return
        row = ent_batch.get(cid)
        if row is None:
            ent_batch[cid] = {"id": cid, "label": ent["type"], "name": ent["name"],
                              "aliases": ent["aliases"], "prov": prov, "chunk": chunk}
        else:
            row["prov"], row["chunk"] = prov, chunk
            if len(ent["aliases"]) > len(row["aliases"]):
                row["aliases"] = ent["aliases"]

    def flush() -> None:
        if ent_batch:
            totals["nodes"] += len(ent_batch)
            _write_entities(graph, list(ent_batch.values()))
            ent_batch.clear()
        if ev_batch:
            _write_events(graph, ev_batch)
            ev_batch.clear()
        if rel_batch:
            _write_rels(graph, rel_batch)
            rel_batch.clear()
        if ledger_batch:
            con = sqlite3.connect(store.path)
            con.executemany(
                "INSERT OR REPLACE INTO load_ledger (chunk_id, model, loaded_at) VALUES (?, ?, ?)",
                ledger_batch,
            )
            con.commit()
            con.close()
            ledger_batch.clear()

    for chunk_id, raw in rows:
        try:
            ex = ChunkExtraction(**json.loads(raw))
        except (ValidationError, json.JSONDecodeError):
            totals["skipped"] += 1
            continue
        doc = _doc_for_chunk(doc_by_id, chunk_id)
        if doc is None:
            totals["skipped"] += 1
            continue
        if doc_prefix and not doc["document_id"].startswith(doc_prefix):
            continue
        prov = {
            "chunk_id": chunk_id,
            "document_id": doc["document_id"],
            "source": doc.get("title"),
            "source_type": doc.get("type"),
            "timeline_id": doc.get("timeline_id"),
        }
        prov_json = json.dumps(prov)

        for ent in ex.entities:
            cid = resolver.register(ent.name, ent.type.value, ent.aliases)
            queue_entity(cid, prov_json, chunk_id)
            totals["entities"] += 1

        for ev in ex.events:
            ev_id = resolver.register(ev.name, "Event")
            ev_batch.append({
                "id": ev_id, "name": ev.name,
                "date": ev.date, "date_precision": ev.date_precision,
                "location": ev.location, "evidence_quote": ev.evidence_quote,
                "prov": prov_json, "chunk": chunk_id,
                "timeline": f"timeline:{doc.get('timeline_id')}",
                "document": doc["document_id"],
            })
            queue_entity(ev_id, prov_json, chunk_id)
            totals["events"] += 1
            for p in ev.participants:
                p_id = resolver.register(p, "Character")
                queue_entity(p_id, prov_json, chunk_id)
                rel_batch.append({"src": p_id, "rel": "PARTICIPATES_IN", "dst": ev_id, "prov": prov_json})
            for o in ev.objects:
                o_id = resolver.register(o, "Object")
                queue_entity(o_id, prov_json, chunk_id)
                rel_batch.append({"src": ev_id, "rel": "INVOLVES", "dst": o_id, "prov": prov_json})
            if ev.location:
                loc_id = resolver.register(ev.location, "Location")
                queue_entity(loc_id, prov_json, chunk_id)
                rel_batch.append({"src": ev_id, "rel": "OCCURS_AT", "dst": loc_id, "prov": prov_json})

        for rel in ex.relations:
            # registered endpoints are queued as node writes, so edges never dangle
            src_id = resolver.register(rel.source, "Character")
            dst_id = resolver.register(rel.target, "Character")
            queue_entity(src_id, prov_json, chunk_id)
            queue_entity(dst_id, prov_json, chunk_id)
            if src_id == dst_id:
                continue
            rel_batch.append({"src": src_id, "rel": rel.relation.value, "dst": dst_id, "prov": prov_json})
            totals["relations"] += 1

        for t in ex.temporals:
            a_id = resolver.register(t.event_a, "Event")
            b_id = resolver.register(t.event_b, "Event")
            queue_entity(a_id, prov_json, chunk_id)
            queue_entity(b_id, prov_json, chunk_id)
            if a_id == b_id:
                continue
            if t.relation == "AFTER":
                a_id, b_id = b_id, a_id  # canonical direction: BEFORE edges only
            rel_batch.append({"src": a_id, "rel": t.relation if t.relation != "AFTER" else "BEFORE",
                              "dst": b_id, "prov": prov_json})
            totals["temporals"] += 1

        totals["chunks"] += 1
        ledger_batch.append((chunk_id, model, datetime.now(timezone.utc).isoformat()))
        if len(ent_batch) + len(ev_batch) + len(rel_batch) + len(ledger_batch) >= BATCH:
            flush()

    flush()
    resolver.flush()
    logger.info("loaded: %s", totals)
    return totals


def _doc_for_chunk(doc_by_id: dict[str, dict], chunk_id: str) -> dict | None:
    doc_id = chunk_id.split("#")[0] if "#" in chunk_id else None
    return doc_by_id.get(doc_id)


def _load_documents(graph: Graph, docs: list[dict], doc_prefix: str | None) -> None:
    """Create Movie/Series/Episode nodes with timeline + DEPICTED_IN edges."""
    with graph.session() as s:
        for d in docs:
            if doc_prefix and not d["document_id"].startswith(doc_prefix):
                continue
            if d["type"] == "movie":
                s.run(
                    """MERGE (m:Movie {id: $id})
                       ON CREATE SET m.name = $name, m.year = $year, m.timeline = $tl,
                                      m.canonical = $canon
                       WITH m
                       MATCH (t:Timeline {id: $tlid})
                       MERGE (m)-[:DEPICTED_IN]->(t)""",
                    id=d["document_id"], name=d["title"], year=d["year"],
                    tl=d["timeline_id"], canon=d.get("canonical", 1),
                    tlid=f"timeline:{d['timeline_id']}",
                )
            else:
                if d.get("season") is not None:
                    s.run(
                        """MERGE (e:Episode {id: $id})
                           ON CREATE SET e.name = $name, e.year = $year, e.timeline = $tl,
                                          e.season = $season, e.episode = $episode
                           WITH e
                           MATCH (t:Timeline {id: $tlid})
                           MERGE (e)-[:DEPICTED_IN]->(t)""",
                        id=d["document_id"], name=d["title"], year=d["year"],
                        tl=d["timeline_id"], season=d["season"], episode=d["episode"],
                        tlid=f"timeline:{d['timeline_id']}",
                    )
                else:
                    s.run(
                        """MERGE (s:Series {id: $id})
                           ON CREATE SET s.name = $name, s.year = $year, s.timeline = $tl,
                                          s.canonical = $canon
                           WITH s
                           MATCH (t:Timeline {id: $tlid})
                           MERGE (s)-[:DEPICTED_IN]->(t)""",
                        id=d["document_id"], name=d["title"], year=d["year"],
                        tl=d["timeline_id"], canon=d.get("canonical", 1),
                        tlid=f"timeline:{d['timeline_id']}",
                    )


def _write_entities(graph: Graph, batch: list[dict]) -> None:
    with graph.session() as s:
        # one UNWIND per label
        by_label: dict[str, list] = defaultdict(list)
        for b in batch:
            if b["label"] not in NODE_LABELS:
                logger.warning("skipping node with unknown label %r (%s)", b["label"], b["id"])
                continue
            by_label[b["label"]].append(b)
        for label, rows in by_label.items():
            s.run(
                f"""UNWIND $rows AS r
                    MERGE (n:{label} {{id: r.id}})
                    ON CREATE SET n.name = r.name, n.created_at = timestamp()
                    SET n.aliases = CASE
                            WHEN size(coalesce(r.aliases, [])) > size(coalesce(n.aliases, []))
                            THEN r.aliases ELSE coalesce(n.aliases, []) END,
                        n.provenance = r.prov, n.last_chunk = r.chunk""",
                rows=rows,
            )


def _write_events(graph: Graph, batch: list[dict]) -> None:
    with graph.session() as s:
        stats = s.run(
            """UNWIND $rows AS r
               MERGE (n:Event {id: r.id})
               ON CREATE SET n.name = r.name, n.created_at = timestamp()
               SET n.date = r.date, n.date_precision = r.date_precision,
                   n.evidence_quote = r.evidence_quote, n.provenance = r.prov,
                   n.last_chunk = r.chunk
               WITH n, r
               OPTIONAL MATCH (t:Timeline {id: r.timeline})
               WITH n, r, t
               OPTIONAL MATCH (x) WHERE (x:Movie OR x:Episode OR x:Series) AND x.id = r.document
               FOREACH (_ IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
                   MERGE (n)-[:OCCURS_IN]->(t))
               FOREACH (_ IN CASE WHEN x IS NOT NULL THEN [1] ELSE [] END |
                   MERGE (n)-[:DEPICTED_IN]->(x))
               RETURN sum(CASE WHEN t IS NULL THEN 1 ELSE 0 END) AS missing_timeline,
                      sum(CASE WHEN x IS NULL THEN 1 ELSE 0 END) AS missing_document""",
            rows=batch,
        ).single()
    if stats["missing_timeline"]:
        logger.warning("%d events reference an unseeded Timeline — seed_timelines first",
                       stats["missing_timeline"])
    if stats["missing_document"]:
        logger.warning("%d events reference a missing Movie/Episode/Series document node",
                       stats["missing_document"])


def _write_rels(graph: Graph, batch: list[dict]) -> None:
    with graph.session() as s:
        by_rel: dict[str, list] = defaultdict(list)
        for b in batch:
            by_rel[b["rel"]].append(b)
        for rel, rows in by_rel.items():
            written = s.run(
                f"""UNWIND $rows AS r
                    OPTIONAL MATCH (a) WHERE (a:Character OR a:Event OR a:Movie OR a:Series
                                              OR a:Episode OR a:Location OR a:Object
                                              OR a:Organization) AND a.id = r.src
                    OPTIONAL MATCH (b) WHERE (b:Character OR b:Event OR b:Movie OR b:Series
                                              OR b:Episode OR b:Location OR b:Object
                                              OR b:Organization) AND b.id = r.dst
                    WITH r, a, b WHERE a IS NOT NULL AND b IS NOT NULL
                    MERGE (a)-[e:{rel}]->(b)
                    ON CREATE SET e.provenance = r.prov, e.created_at = timestamp()
                    RETURN count(e) AS written""",
                rows=rows,
            ).single()["written"]
            if written < len(rows):
                logger.warning("rel %s: %d/%d rows had a missing endpoint node",
                               rel, len(rows) - written, len(rows))
