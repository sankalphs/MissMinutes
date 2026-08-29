"""Hybrid retrieval + reranking (spec:13,23).

Merges: FTS5 lexical + Qdrant semantic + Neo4j graph traversal + entity
lookup. Graph/temporal evidence outranks pure cosine similarity.
"""
import json
import logging
from typing import Any

from src.graph.schema import Graph
from src.ingestion.store import Store
from src.search.planner import QueryPlan
from src.vector.qdrant import VectorStore, embed_query

logger = logging.getLogger(__name__)


def lexical_search(store: Store, plan: QueryPlan, limit: int = 10) -> list[dict]:
    terms = plan.entities[:6]
    if not terms:
        return []
    joined = " OR ".join(f'"{t}"' for t in terms)
    try:
        return store.fts_search(joined, limit=limit)
    except Exception:
        return []


def semantic_search(vs: VectorStore, plan: QueryPlan, query: str, limit: int = 10) -> list[dict]:
    try:
        vec = embed_query(query)
        return vs.search(vec, limit=limit, timeline=plan.timeline)
    except Exception as e:
        logger.warning("semantic search failed: %s", e)
        return []


def graph_search(graph: Graph, plan: QueryPlan, limit: int = 20) -> list[dict]:
    """Resolve plan entities to graph nodes + traverse temporal edges."""
    results: list[dict] = []
    with graph.session() as s:
        for name in plan.entities[:4]:
            rows = s.run(
                """MATCH (n) WHERE toLower(n.name) = toLower($name)
                   OPTIONAL MATCH (n)-[r]-(m)
                   WITH n, m, r
                   LIMIT 30
                   RETURN n.id AS id, n.name AS name, labels(n)[0] AS label,
                          [x IN collect({id: m.id, name: m.name, rel: type(r)}) WHERE x.id IS NOT NULL | x][..6] AS neighbors
                   LIMIT 5""",
                name=name,
            ).data()
            results.extend(rows)
        if plan.operation in ("next_events", "prev_events") and plan.reference_event:
            direction = "BEFORE" if plan.operation == "next_events" else "AFTER"
            rows = s.run(
                f"""MATCH (a:Event)-[:{direction}*1..4]->(b:Event)
                    WHERE toLower(a.name) CONTAINS toLower($ref)
                    RETURN b.id AS id, b.name AS name, 'Event' AS label,
                           b.date_precision AS precision, b.date AS date
                    ORDER BY coalesce(b.date, '9999') LIMIT $limit""",
                ref=plan.reference_event, limit=limit,
            ).data()
            results.extend(rows)
        if plan.operation == "find_connection" and len(plan.entities) >= 2:
            rows = s.run(
                """MATCH p = (a)-[*1..3]-(b)
                   WHERE toLower(a.name) CONTAINS toLower($e1)
                     AND toLower(b.name) CONTAINS toLower($e2)
                   RETURN [n IN nodes(p) | n.name] AS path LIMIT 5""",
                e1=plan.entities[0], e2=plan.entities[1],
            ).data()
            results.extend({"path": r["path"]} for r in rows)
    return results


def rerank(plan: QueryPlan, query: str, lex: list[dict], sem: list[dict],
           graph_hits: list[dict]) -> dict[str, Any]:
    """Combine scores: graph > semantic > lexical; dedupe by chunk_id."""
    combined: dict[str, dict] = {}

    for h in graph_hits:
        if "path" in h:
            combined[f"path:{h['path'][0]}:{h['path'][-1]}"] = {
                "type": "path", "score": 1.0, "data": h
            }
        else:
            combined[h["id"]] = {
                "type": "entity", "score": 0.9, "data": h
            }

    for i, h in enumerate(sem):
        cid = h.get("chunk_id")
        if cid and cid not in combined:
            combined[cid] = {
                "type": "chunk",
                "score": 0.4 + (0.2 * (len(sem) - i) / max(len(sem), 1)),
                "data": h,
            }

    for i, h in enumerate(lex):
        cid = h.get("chunk_id")
        if cid in combined and combined[cid]["type"] == "chunk":
            combined[cid]["score"] += 0.1
        elif cid:
            combined[cid] = {"type": "chunk", "score": 0.3, "data": h}

    ranked = sorted(combined.values(), key=lambda x: -x["score"])
    return {
        "plan": plan.model_dump(),
        "results": ranked[:20],
    }


def hybrid_search(store: Store, vs: VectorStore, graph: Graph, query: str,
                  plan: QueryPlan) -> dict[str, Any]:
    lex = lexical_search(store, plan)
    sem = semantic_search(vs, plan, query)
    gph = graph_search(graph, plan)
    return rerank(plan, query, lex, sem, gph)
