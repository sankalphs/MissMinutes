"""Offline retrieval-quality eval over a golden question set (Phase 8).

Runs the REAL retrieval stack — deterministic plan -> hybrid_search — with
no LLM in the loop, then scores each variant against golden answers:

  - doc hit      : a retrieved chunk comes from the golden document
  - chunk hit    : retrieved chunk overlaps the golden cue window (exact)
                   or its ±1-neighbour padded window (adjacent)
  - evidence@6   : golden doc present in the top-6 rows the LLM would see,
                   graph rows included (displacement counted honestly)

Window-overlap matching (not chunk_id equality) is what lets the same
fixture judge re-chunked corpora: a golden window falls inside whatever
chunk now covers it. Metrics: recall@1/3/6/12, MRR@12, nDCG@12 (gains
0/1/2/3), plus per-leg diagnostics so a regression names its leg.

Usage:
  python -m src.eval.retrieval_eval                    # baseline run
  MM_EVAL_LEXICAL=full_bm25 python -m src.eval.retrieval_eval
  python -m src.eval.retrieval_eval --no-graph --out data/processed/eval_x.json
"""
import argparse
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.config import settings
from src.ingestion.store import Store
from src.search.hybrid import hybrid_search, lexical_search, semantic_search
from src.search.planner import QueryPlan

KS = (1, 3, 6, 12)

# sentence-initial / filler words never make a usable entity span
_QWORD = {
    "what", "who", "whom", "when", "where", "how", "why", "which", "whose",
    "did", "do", "does", "is", "are", "was", "were", "the", "a", "an",
    "in", "on", "of", "to", "after", "before", "with", "and", "or", "can",
    "could", "tell", "about", "there", "it", "its", "happen", "happened",
    "cause", "caused", "does", "belong", "made", "create", "created",
}

_CAP_SPAN = re.compile(r"[A-Z][a-zA-Z'.-]*(?:\s+[A-Z][a-zA-Z'.-]*){0,3}")


def extract_entities(query: str) -> list[str]:
    """Deterministic stand-in for the LLM planner: maximal capitalized
    spans, trimmed of question words. Identical across every variant, so
    planner noise cannot skew a comparison."""
    out: list[str] = []
    for span in _CAP_SPAN.findall(query):
        words = span.split()
        while words and words[0].lower() in _QWORD:
            words = words[1:]
        while words and words[-1].lower() in _QWORD:
            words = words[:-1]
        if words:
            out.append(" ".join(words))
    return out[:6]


@dataclass
class Case:
    id: str
    kind: str            # chunk | doc
    q: str
    document_id: str
    chunk_id: str | None
    window: tuple[float, float] | None
    ext_window: tuple[float, float] | None
    timeline: str | None
    source: str


@dataclass
class LegHits:
    """Per-leg golden-doc hits for diagnostics (shared windows)."""
    docs: set[str] = field(default_factory=set)


def load_fixture(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Case(
            id=c["id"], kind=c["kind"], q=c["q"], document_id=c["document_id"],
            chunk_id=c.get("chunk_id"),
            window=tuple(c["window"]) if c.get("window") else None,
            ext_window=tuple(c["ext_window"]) if c.get("ext_window") else None,
            timeline=c.get("timeline"), source=c.get("source", "gmi"),
        )
        for c in raw["cases"]
    ]


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def grade_row(case: Case, row: dict) -> int:
    """Relevance grade of one retrieved row: 3 golden chunk window overlap,
    2 adjacent (±1-chunk padded) window, 1 same document only, 0 no match.
    Rows without timecodes can still earn doc-level credit (grade 1)."""
    if row.get("document_id") != case.document_id:
        return 0
    if case.window is None or row.get("start_s") is None or row.get("end_s") is None:
        return 1
    w = (row["start_s"], row["end_s"])
    if _overlap(w, case.window):
        return 3
    if case.ext_window and _overlap(w, case.ext_window):
        return 2
    return 1


def _dcg(grades: list[int]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(grades))


def evaluate_cases(cases: list[Case], rows_by_id: dict[str, list[dict]]) -> dict:
    """Score the final ranked rows per case (row types other than chunk
    simply never match a document, so graph displacement is counted)."""
    agg = {
        "doc_recall": {k: 0 for k in KS}, "chunk_recall": {k: 0 for k in KS},
        "evidence6_doc": 0, "doc_mrr": 0.0, "chunk_mrr": 0.0, "ndcg": 0.0,
    }
    n_chunk_kind = 0
    per_case = []
    for case in cases:
        rows = rows_by_id[case.id][:12]
        grades = [grade_row(case, r) for r in rows]

        # golden doc inside the top-6 pool the LLM would actually see
        ev6 = 1 if any(g >= 1 for g in grades[:6]) else 0

        doc_rr = next((1.0 / (i + 1) for i, g in enumerate(grades) if g >= 1), 0.0)
        chunk_rr = next((1.0 / (i + 1) for i, g in enumerate(grades) if g >= 2), 0.0)

        if case.kind == "chunk":
            n_chunk_kind += 1
            agg["chunk_mrr"] += chunk_rr
        agg["doc_mrr"] += doc_rr
        agg["ndcg"] += (
            _dcg(grades) / _dcg(sorted(grades, reverse=True)) if any(grades) else 0.0
        )
        agg["evidence6_doc"] += ev6
        for k in KS:
            if any(g >= 1 for g in grades[:k]):
                agg["doc_recall"][k] += 1
            if case.kind == "chunk" and any(g >= 2 for g in grades[:k]):
                agg["chunk_recall"][k] += 1
        per_case.append({
            "id": case.id, "q": case.q,
            "chunk_grade": max(grades) if case.kind == "chunk" else None,
            "doc_grade": 1 if any(grades) else 0,
            "first_hit_rank": next((i + 1 for i, g in enumerate(grades) if g >= 1), None),
            "evidence6": ev6,
        })

    n = max(len(cases), 1)
    nc = max(n_chunk_kind, 1)
    summary = {
        "cases": len(cases),
        "chunk_cases": n_chunk_kind,
        "evidence6_doc_recall": round(agg["evidence6_doc"] / n, 4),
        "doc_recall@1": round(agg["doc_recall"][1] / n, 4),
        "doc_recall@3": round(agg["doc_recall"][3] / n, 4),
        "doc_recall@6": round(agg["doc_recall"][6] / n, 4),
        "doc_recall@12": round(agg["doc_recall"][12] / n, 4),
        "chunk_recall@1": round(agg["chunk_recall"][1] / nc, 4),
        "chunk_recall@3": round(agg["chunk_recall"][3] / nc, 4),
        "chunk_recall@6": round(agg["chunk_recall"][6] / nc, 4),
        "chunk_recall@12": round(agg["chunk_recall"][12] / nc, 4),
        "doc_mrr@12": round(agg["doc_mrr"] / n, 4),
        "chunk_mrr@12": round(agg["chunk_mrr"] / nc, 4),
        "ndcg@12": round(agg["ndcg"] / n, 4),
    }
    # primary decision metric: the evidence the LLM sees (top-6) first,
    # deeper pool + ranking quality as tiebreakers
    summary["primary"] = round(
        0.5 * summary["evidence6_doc_recall"]
        + 0.25 * summary["chunk_recall@6"]
        + 0.25 * summary["chunk_mrr@12"], 4,
    )
    return {"summary": summary, "per_case": per_case}


def run_eval(fixture: Path, no_graph: bool = False, legs: bool = False,
             limit: int | None = None) -> dict:
    cases = load_fixture(fixture)
    if limit:
        cases = cases[:limit]
    store = Store()
    from src.vector.qdrant import VectorStore

    vs = VectorStore()
    graph = None
    if not no_graph:
        from src.graph.schema import Graph

        graph = Graph()

    rows_by_id: dict[str, list[dict]] = {}
    leg_stats: dict[str, dict] = {}
    t0 = time.time()
    for case in cases:
        plan = QueryPlan(entities=extract_entities(case.q), intent="semantic",
                         operation="free_search")
        ranked = hybrid_search(store, vs, graph, case.q, plan)
        # enrich chunk rows with timecodes so window matching works — the
        # hybrid path does not carry start_s/end_s today, the store does
        for r in ranked["results"]:
            if r["type"] == "chunk" and r["data"].get("start_s") is None:
                cid = r["data"].get("chunk_id")
                if cid:
                    full = store.get_chunk_times(cid)
                    if full:
                        r["data"].update(full)
        rows_by_id[case.id] = [r["data"] for r in ranked["results"]]

        if legs:
            for name, res in (
                ("lexical", lexical_search(store, plan, case.q)[0]),
                ("semantic", semantic_search(vs, plan, case.q)[0]),
            ):
                st = leg_stats.setdefault(name, {"hit": 0, "n": 0})
                st["n"] += 1
                if any(h.get("document_id") == case.document_id for h in res[:6]):
                    st["hit"] += 1

    report = evaluate_cases(cases, rows_by_id)
    report["summary"]["wall_s"] = round(time.time() - t0, 1)
    if legs:
        report["legs_top6_doc_recall"] = {
            k: round(v["hit"] / max(v["n"], 1), 4) for k, v in leg_stats.items()
        }
    report["config"] = {
        k: os.getenv(k) for k in (
            "EMBEDDING_MODEL", "QDRANT_COLLECTION", "QDRANT_LOCAL_PATH",
        ) if os.getenv(k)
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path,
                    default=Path(__file__).parent / "fixtures" / "golden_retrieval.json")
    ap.add_argument("--out", type=Path,
                    default=settings.PROCESSED_DIR / "retrieval_eval_report.json")
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--legs", action="store_true", help="per-leg diagnostic metrics")
    ap.add_argument("--limit", type=int, help="smoke-run only the first N cases")
    args = ap.parse_args()

    report = run_eval(args.fixture, no_graph=args.no_graph, legs=args.legs,
                      limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    if "legs_top6_doc_recall" in report:
        print("per-leg top6 doc recall:", json.dumps(report["legs_top6_doc_recall"]))
    print(f"full report: {args.out}")


if __name__ == "__main__":
    main()
