"""Hybrid retrieval + reranking (spec:13,23).

Merges: FTS5 lexical + Qdrant semantic + Neo4j graph traversal + entity
lookup. Grounded subtitle chunks outrank synthetic graph evidence; graph
structure informs, it does not drown the passages it was extracted from.

Scope truth (PRODUCT principle 2): when plan.timeline is set, EVERY leg
searches only that branch — no silent unscoped fallback, ever.

Leg health is tri-state — ok (served hits), empty (healthy, nothing on
this query/branch), down (backend unreachable) — so the status line can
tell "no files" from "backend down" and name the leg that died.
"""
import logging
import os
import re
from typing import Any

from neo4j import Query

from src.graph.schema import Graph
from src.ingestion.store import Store
from src.search.planner import QueryPlan
from src.vector.qdrant import VectorStore, embed_query

logger = logging.getLogger(__name__)

# a runaway graph query must die server-side, not hang the worker thread
_CYPHER_TIMEOUT_S = 8.0

# --- experiment knobs (eval-only; integration keeps the winning mode) ------
# MM_EVAL_LEXICAL: current | bm25 | full_bm25 | full_bm25_k10
# MM_EVAL_FUSION:  current | rrf | weighted   (alpha via MM_EVAL_FUSION_ALPHA)
# MM_EVAL_RERANKER: none | bge | msmarco      (implemented in src/search/rerank.py)
LEXICAL_MODE = os.getenv("MM_EVAL_LEXICAL", "current")
FUSION_MODE = os.getenv("MM_EVAL_FUSION", "current")
FUSION_ALPHA = float(os.getenv("MM_EVAL_FUSION_ALPHA", "0.5"))
RERANKER = os.getenv("MM_EVAL_RERANKER", "none")

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "with", "and", "or",
    "is", "was", "were", "did", "do", "does", "after", "before", "that",
    "what", "who", "when", "where", "how", "why", "which", "whose", "whom",
    "are", "can", "could", "happen", "happened", "happens", "caused", "cause",
    "made", "make", "belong", "belongs", "tell", "about", "there", "their",
    "from", "this", "these", "those", "have", "has", "had", "get", "got",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9'-]+", text.lower()) if t not in _STOPWORDS and len(t) > 2]


# --------------------------------------------------------------------------
# lexical leg
# --------------------------------------------------------------------------

def lexical_search(store: Store, plan: QueryPlan, query: str, limit: int = 10) -> tuple[list[dict], str]:
    """FTS5 lexical search; scoped to plan.timeline when set.

    Modes (MM_EVAL_LEXICAL):
      current      — entity phrases only, insertion order (the old behavior)
      bm25         — entity phrases, ranked by bm25
      full_bm25    — entity phrases + raw-query content tokens, bm25, 20 hits
      full_bm25_k10— full_bm25 with the standard 10-hit cap

    Exceptions propagate — a dead lexical leg must be reported, not
    swallowed (the old silent `return []` masked a thread-unsafe Store).
    """
    if LEXICAL_MODE == "current":
        terms = [_fts_safe(t) for t in plan.entities[:6]]
        terms = [t for t in terms if t]
        joined = " OR ".join(f'"{t}"' for t in terms)
    else:
        joined = _lexical_query(plan, query)
        if not joined:
            return [], "empty"
        if LEXICAL_MODE == "full_bm25":
            limit = 20
    if not joined:
        return [], "empty"
    try:
        hits = store.fts_search(joined, limit=limit, timeline=plan.timeline,
                                rank=LEXICAL_MODE != "current",
                                raw=LEXICAL_MODE != "current")
    except Exception as e:
        logger.warning("lexical search failed: %s", e)
        return [], "down"
    for h in hits:
        h["source"] = "fts"
    return hits, ("ok" if hits else "empty")


def _lexical_query(plan: QueryPlan, query: str) -> str:
    """Ranked-mode MATCH expression: entity phrases OR'd with the raw
    query's content tokens. Entities carry proper names the tokenizer
    would split ('Doctor Strange'); query tokens cover everything the
    planner missed. Order-preserving dedup, capped to keep MATCH sane."""
    terms: list[str] = []
    for t in plan.entities[:6]:
        safe = _fts_safe(t)
        if safe and safe.lower() not in [x.lower() for x in terms]:
            terms.append(safe)
    for tok in re.findall(r"[a-z0-9'-]+", query.lower()):
        if len(tok) > 2 and tok not in _STOPWORDS:
            safe = _fts_safe(tok)
            if safe and safe.lower() not in [x.lower() for x in terms]:
                terms.append(safe)
        if len(terms) >= 14:
            break
    return " OR ".join(f'"{t}"' for t in terms)


def _fts_safe(term: str) -> str:
    """FTS5-safe: strip quote chars, keep alphanumerics/hyphens."""
    return re.sub(r"[^\w\s\-']", "", term).strip()


# --------------------------------------------------------------------------
# semantic leg
# --------------------------------------------------------------------------

def semantic_search(vs: VectorStore, plan: QueryPlan, query: str, limit: int = 10) -> tuple[list[dict], str]:
    try:
        vec = embed_query(query)
        # scope is truthful: an empty branch stays empty — no unscoped fallback
        hits = vs.search(vec, limit=limit, timeline=plan.timeline)
    except Exception as e:
        logger.warning("semantic search failed: %s", e)
        return [], "down"
    return hits, ("ok" if hits else "empty")


# --------------------------------------------------------------------------
# graph leg
# --------------------------------------------------------------------------

def graph_search(graph: Graph, plan: QueryPlan, limit: int = 20) -> tuple[list[dict], str]:
    """Resolve plan entities to graph nodes + traverse temporal edges.

    Temporal edges are stored canonically as BEFORE (a)-[:BEFORE]->(b)
    means a happened before b. 'What happened after X' walks X<-[:BEFORE]-next;
    'before X' walks X-[:BEFORE]->prev.

    Degrades to empty on any graph outage — a dead Aura instance must never
    kill a search that FTS5 + Qdrant evidence can still answer. Scoped
    plans resolve entities only through events/movies on that timeline.
    """
    results: list[dict] = []
    try:
        with graph.session() as s:
            _graph_queries(s, plan, limit, results)
    except Exception as e:
        logger.warning("graph search failed (degrading to vector+lexical): %s", e)
        return [], "down"
    return results, ("ok" if results else "empty")


def _graph_queries(s, plan: QueryPlan, limit: int, results: list[dict]) -> None:
    tl = f"timeline:{plan.timeline}" if plan.timeline else None
    for name in plan.entities[:4]:
        rows = _entity_lookup(s, name)
        if tl:
            # scope truth: keep only entities witnessed on this timeline
            rows = _scoped_entity_rows(s, rows, tl, name)
        results.extend(rows)
    if plan.operation in ("next_events", "prev_events") and plan.reference_event:
        results.extend(_event_walk(s, plan, limit))
    if plan.operation == "find_connection" and len(plan.entities) >= 2:
        results.extend(_find_connection(s, plan.entities[0], plan.entities[1]))
    return results


_ENTITY_NEIGHBORS = """MATCH (n) WHERE n.id IN $ids
                     OPTIONAL MATCH (n)-[r]-(m)
                     WITH n, m, r
                     LIMIT 30
                     RETURN n.id AS id, n.name AS name, labels(n)[0] AS label,
                            [x IN collect({id: m.id, name: m.name, rel: type(r)}) WHERE x.id IS NOT NULL | x][..6] AS neighbors
                     LIMIT 5"""


_ENTITY_LABEL_RANK = {
    "Character": 0, "Object": 1, "Organization": 2, "Location": 3,
    "Event": 4, "Series": 5, "Movie": 6, "Episode": 7, "Timeline": 8,
}


def _entity_lookup(s, name: str, cap: int = 4) -> list[dict]:
    """Resolve an entity by name. Exact matches first, fuzzy CONTAINS
    second — and among candidates, a Character named 'Loki' outranks
    the episode also named 'Loki' (a bare name in a question means the
    entity, not the show it appeared in)."""
    nl = (name or "").strip().lower()
    if not nl:
        return []

    def _fetch(where: str) -> list[dict]:
        return s.run(
            Query(
                f"MATCH (n) WHERE {where} "
                "RETURN n.id AS id, n.name AS name, labels(n)[0] AS label LIMIT 24",
                timeout=_CYPHER_TIMEOUT_S,
            ),
            nl=nl,
        ).data()

    cands = _fetch("toLower(n.name) = $nl")
    if not cands:
        cands = _fetch("toLower(n.name) CONTAINS $nl")
    if not cands:
        return []
    cands.sort(key=lambda r: _ENTITY_LABEL_RANK.get(r["label"], 9))
    rows: list[dict] = []
    for r in cands[:cap]:
        # one bounded neighbor fetch per candidate, in priority order —
        # the character's row can never be pushed out by index-scan order
        got = s.run(Query(_ENTITY_NEIGHBORS, timeout=_CYPHER_TIMEOUT_S), ids=[r["id"]]).data()
        rows.extend(got)
    return rows[:cap]


def _scoped_entity_rows(s, rows: list[dict], tl: str, name: str) -> list[dict]:
    """An entity belongs to the branch only if an event on that timeline
    (or a movie/episode depicting it) touches it — verified per row."""
    if not rows:
        return []
    try:
        witnessed = s.run(
            Query(
                """MATCH (n) WHERE n.id IN $ids
                   MATCH (n)-[:PARTICIPATES_IN|INVOLVES|OCCURS_AT]-(m)
                   WHERE (m:Event AND (m)-[:OCCURS_IN]->(:Timeline {id: $tl}))
                      OR (m:Movie AND (m)-[:DEPICTED_IN]->(:Timeline {id: $tl}))
                      OR (m:Episode AND (m)-[:DEPICTED_IN]->(:Timeline {id: $tl}))
                   RETURN DISTINCT n.id AS id LIMIT $cap""",
                timeout=_CYPHER_TIMEOUT_S,
            ),
            ids=[r["id"] for r in rows], tl=tl, cap=len(rows),
        ).data()
    except Exception as e:
        logger.warning("scoped entity check failed for %r: %s", name, e)
        return []
    if not witnessed:
        return []
    witnessed_ids = {w["id"] for w in witnessed}
    return [row for row in rows if row["id"] in witnessed_ids]


def _event_walk(s, plan: QueryPlan, limit: int) -> list[dict]:
    """next_events: events AFTER the reference = incoming BEFORE edges.
    prev_events: events BEFORE the reference = outgoing BEFORE edges.

    Event matching is token-overlap based (B6): the longest query token
    seeds a bounded CONTAINS scan, then Python scores full overlap —
    'escaped with' still finds 'Loki steals the Tesseract'.
    """
    ref_tokens = _tokens(plan.reference_event)
    if not ref_tokens:
        return []
    seed = max(ref_tokens, key=len)
    pattern = (
        "(ref)-[:BEFORE*1..3]->(b)" if plan.operation == "next_events"
        else "(b)-[:BEFORE*1..3]->(ref)"
    )
    try:
        rows = s.run(
            Query(
                f"""MATCH (ref:Event) WHERE toLower(ref.name) CONTAINS $seed
                    MATCH {pattern}
                    RETURN DISTINCT b.id AS id, b.name AS name, 'Event' AS label,
                           ref.name AS ref, b.date_precision AS precision, b.date AS date
                    LIMIT $limit""",
                timeout=_CYPHER_TIMEOUT_S,
            ),
            seed=seed, limit=max(limit, 20),
        ).data()
    except Exception as e:
        logger.warning("event walk failed: %s", e)
        return []

    scored = []
    for r in rows:
        ref_name = (r.get("ref") or "").lower()
        overlap = sum(1 for t in ref_tokens if t in ref_name)
        if overlap >= max(1, len(ref_tokens) // 2):
            r.pop("ref", None)
            scored.append(r)
    return scored[:limit]


def _find_connection(s, e1: str, e2: str) -> list[dict]:
    """Bounded connection query: cap endpoint candidates, then shortestPath.

    The old `MATCH p = (a)-[*1..3]-(b)` enumerated undirected paths over
    50k nodes before filtering — a cartesian explosion that took Aura
    down for the rest of the process lifetime. Endpoints resolve by
    token-overlap fallback first ('Fox X-Men' still finds 'X-Men')."""
    a_ids = _resolve_endpoint(s, e1)
    b_ids = _resolve_endpoint(s, e2)
    if not a_ids or not b_ids or set(a_ids) & set(b_ids):
        return []
    rows = s.run(
        Query(
            """UNWIND $pairs AS pair
               MATCH (a {id: pair[0]}), (b {id: pair[1]})
               MATCH p = shortestPath((a)-[*..5]-(b))
               RETURN [n IN nodes(p) | n.name] AS path LIMIT 3""",
            timeout=_CYPHER_TIMEOUT_S,
        ),
        pairs=[[a, b] for a in a_ids[:2] for b in b_ids[:2]],
    ).data()
    return [{"path": r["path"]} for r in rows]


def _resolve_endpoint(s, entity: str, cap: int = 3) -> list[str]:
    """Endpoint candidates: substring name match first, then token overlap
    ('Fox X-Men' -> 'X-Men'), both capped, id-based, characters first
    (a connection question about Loki means the god, not his show)."""
    e = (entity or "").strip().lower()
    if not e:
        return []
    rows = s.run(
        Query(
            """MATCH (a) WHERE a.name IS NOT NULL AND (
                   toLower(a.name) CONTAINS $e OR $e CONTAINS toLower(a.name)
               )
               RETURN a.id AS id, labels(a)[0] AS label, toLower(a.name) AS nl
               LIMIT $cap""",
            timeout=_CYPHER_TIMEOUT_S,
        ),
        e=e, cap=cap * 4,
    ).data()
    if rows:
        # shorter names are the entity itself ('X-Men', not 'Xavier founds
        # mutant school'); characters/organizations outrank their shows
        rows.sort(key=lambda r: (
            _ENTITY_LABEL_RANK.get(r["label"], 9),
            abs(len(r["nl"]) - len(e)),
        ))
        return [r["id"] for r in rows[:cap]]
    toks = [t for t in _tokens(entity) if len(t) > 2]
    if not toks:
        return []
    rows = s.run(
        Query(
            """MATCH (a) WHERE a.name IS NOT NULL
                   AND ANY(t IN $toks WHERE toLower(a.name) CONTAINS t)
               RETURN a.id AS id, labels(a)[0] AS label,
                      [t IN $toks WHERE toLower(a.name) CONTAINS t] AS hits
               ORDER BY size(hits) DESC
               LIMIT $cap""",
            timeout=_CYPHER_TIMEOUT_S,
        ),
        toks=toks, cap=cap * 4,
    ).data()
    rows.sort(key=lambda r: (_ENTITY_LABEL_RANK.get(r["label"], 9), -len(r["hits"])))
    return [r["id"] for r in rows[:cap]]


# --------------------------------------------------------------------------
# rerank
# --------------------------------------------------------------------------

_RRF_K = 60


def _graph_rows(graph_hits: list[dict]) -> list[dict]:
    """Graph evidence rows with the production fixed scores — synthetic rows
    are capped (paths<=2, entities<=3) so grounded subtitle passages keep
    the majority of the evidence the LLM sees (PRODUCT principle)."""
    graph_rows: list[dict] = []
    for h in graph_hits:
        if "path" in h:
            graph_rows.append({
                "key": f"path:{h['path'][0]}:{h['path'][-1]}",
                "entry": {"type": "path", "score": 0.95, "data": h},
            })
        elif h.get("label") == "Event" and ("date" in h or "precision" in h):
            graph_rows.append({
                "key": h["id"],
                "entry": {"type": "entity", "score": 0.62, "data": h},
            })
        else:
            graph_rows.append({
                "key": h["id"],
                "entry": {"type": "entity", "score": 0.55, "data": h},
            })
    graph_rows.sort(key=lambda r: -r["entry"]["score"])
    return graph_rows


def _mark_source(entry: dict, leg: str) -> None:
    """Attribution truth: the status line names every leg that served the
    chunk ('fts', 'vector', 'fts+vector')."""
    data = entry["data"]
    legs = entry.setdefault("_legs", [])
    if leg not in legs:
        legs.append(leg)
    data["source"] = "+".join(legs) if legs else leg


def _fuse_rrf(lex: list[dict], sem: list[dict]) -> list[dict]:
    """Reciprocal Rank Fusion: each leg votes 1/(k+rank); no score-scale
    guessing between cosine and bm25."""
    out: dict[str, dict] = {}
    for leg, hits in (("vector", sem), ("fts", lex)):
        for i, h in enumerate(hits, 1):
            cid = h.get("chunk_id")
            if not cid:
                continue
            e = out.setdefault(cid, {"key": cid, "type": "chunk",
                                     "score": 0.0, "data": dict(h)})
            e["score"] += 1.0 / (_RRF_K + i)
            e["data"].setdefault("title", h.get("title"))
            _mark_source(e, leg)
            if leg == "fts" and h.get("bm25") is not None:
                e["data"]["bm25"] = h["bm25"]
    return sorted(out.values(), key=lambda x: -x["score"])


def _fuse_weighted(lex: list[dict], sem: list[dict]) -> list[dict]:
    """Linear blend: alpha*cosine + (1-alpha)*minmax(bm25). Cosine is
    already 0..1; bm25 is minmax-normalized within the leg's hit set
    (rank-decay fallback when bm25 is absent)."""
    out: dict[str, dict] = {}
    bm = [h["bm25"] for h in lex if h.get("bm25") is not None]
    lo, hi = (min(bm), max(bm)) if bm else (0.0, 0.0)

    def lex_norm(h: dict, i: int) -> float:
        if h.get("bm25") is not None and hi > lo:
            return (h["bm25"] - lo) / (hi - lo)
        return (len(lex) - i) / max(len(lex), 1)

    for h in sem:
        cid = h.get("chunk_id")
        if not cid:
            continue
        e = {"key": cid, "type": "chunk",
             "score": FUSION_ALPHA * h.get("score", 0.0), "data": dict(h)}
        _mark_source(e, "vector")
        out[cid] = e
    for i, h in enumerate(lex):
        cid = h.get("chunk_id")
        if not cid:
            continue
        contrib = (1 - FUSION_ALPHA) * lex_norm(h, i)
        e = out.get(cid)
        if e:
            e["score"] += contrib
            if h.get("bm25") is not None:
                e["data"]["bm25"] = h["bm25"]
            _mark_source(e, "fts")
        else:
            e = {"key": cid, "type": "chunk", "score": contrib, "data": dict(h)}
            _mark_source(e, "fts")
            out[cid] = e
    return sorted(out.values(), key=lambda x: -x["score"])


def _rerank_fused(plan: QueryPlan, query: str, lex: list[dict], sem: list[dict],
                  graph_hits: list[dict]) -> dict[str, Any]:
    """Fused ranking: graph rows keep their fixed scores and caps; chunks
    are scored by fusion (rrf/weighted) and optionally re-scored by a
    cross-encoder (MM_EVAL_RERANKER) before the final merge."""
    combined: dict[str, dict] = {}
    graph_rows = _graph_rows(graph_hits)
    paths = [r for r in graph_rows if r["entry"]["type"] == "path"][:2]
    entities = [r for r in graph_rows if r["entry"]["type"] == "entity"][:3]
    for r in paths + entities:
        combined[r["key"]] = r["entry"]

    chunks = (_fuse_weighted(lex, sem) if FUSION_MODE == "weighted"
              else _fuse_rrf(lex, sem))
    if RERANKER != "none":
        from src.search.rerank import cross_encoder_scores

        top = chunks[:24]
        for c, s in zip(top, cross_encoder_scores(query, [c["data"]["text"] for c in top])):
            c["score"] = s
        chunks = sorted(chunks, key=lambda c: -c["score"])
    for c in chunks:
        combined.setdefault(c["key"], c)

    ranked = sorted(combined.values(), key=lambda x: -x["score"])
    return {
        "plan": plan.model_dump(),
        "results": ranked[:20],
    }


def rerank(plan: QueryPlan, query: str, lex: list[dict], sem: list[dict],
           graph_hits: list[dict]) -> dict[str, Any]:
    """Combine scores: paths > grounded chunks > entity/event rows > lexical
    only. Graph evidence informs, it never dominates — synthetic rows
    (neighbor name lists, event names) are capped so grounded subtitle
    passages hold the majority of the evidence the LLM sees (a 20-row
    temporal walk once crowded 5 of 6 slots and hedged the flagship
    answer).

    MM_EVAL_FUSION=rrf|weighted (optionally MM_EVAL_RERANKER) switches to
    score-aware fusion — the current mode keeps the legacy fixed scores."""
    if FUSION_MODE in ("rrf", "weighted") or RERANKER != "none":
        return _rerank_fused(plan, query, lex, sem, graph_hits)

    combined: dict[str, dict] = {}
    graph_rows = _graph_rows(graph_hits)
    paths = [r for r in graph_rows if r["entry"]["type"] == "path"][:2]
    entities = [r for r in graph_rows if r["entry"]["type"] == "entity"][:3]
    for r in paths + entities:
        combined[r["key"]] = r["entry"]

    for i, h in enumerate(sem):
        cid = h.get("chunk_id")
        if cid and cid not in combined:
            combined[cid] = {
                "type": "chunk",
                "score": 0.44 + (0.2 * (len(sem) - i) / max(len(sem), 1)),
                "data": h,
            }

    for h in lex:
        cid = h.get("chunk_id")
        if cid in combined and combined[cid]["type"] == "chunk":
            combined[cid]["score"] += 0.1
            # the chunk was served by BOTH legs — keep the attribution so
            # the status line can name every leg that fed the ruling
            combined[cid]["data"]["source"] = "fts+vector"
        elif cid and cid not in combined:
            combined[cid] = {"type": "chunk", "score": 0.34, "data": h}

    ranked = sorted(combined.values(), key=lambda x: -x["score"])
    return {
        "plan": plan.model_dump(),
        "results": ranked[:20],
    }


def hybrid_search(store: Store, vs: VectorStore, graph: Graph, query: str,
                  plan: QueryPlan) -> dict[str, Any]:
    lex, lex_state = lexical_search(store, plan, query)
    sem, sem_state = semantic_search(vs, plan, query)
    gph, gph_state = graph_search(graph, plan)
    ranked = rerank(plan, query, lex, sem, gph)
    ranked["legs"] = {
        "graph": gph_state,
        "vector": sem_state,
        "lexical": lex_state,
    }
    return ranked
