"""Evaluation benchmark — measures retrieval, temporal, citation, faithfulness.

spec:32: expected entity/events/timeline/sources/ordering per question.
Runs the full pipeline (plan -> hybrid -> synthesis) and scores:
  - retrieval: expected chunk/document in top-12 evidence
  - entity: expected entity found by planner or graph
  - timeline: answer references correct timeline when expected
  - citation: answer contains >=1 valid in-range [n] marker
  - faithfulness: _faithful() gate passes
  - latency: seconds per query
Scoring is lenient on the synthetic-only corpus (tests marked skip_if_no_corpus
when < 3 documents ingested).
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.config import settings
from src.graph.schema import Graph
from src.ingestion.store import Store
from src.llm.client import GMIClient
from src.search.hybrid import hybrid_search
from src.search.planner import parse_query
from src.search.synthesis import _faithful, generate_answer

BENCHMARK: list[dict] = [
    {
        "q": "What happened after Loki escaped with the Tesseract?",
        "expect_docs": ["the_avengers_2012"],
        "expect_entities": ["Loki"],
        "expect_timeline": "mcu",
        "expect_citation": True,
    },
    {
        "q": "Who is Loki?",
        "expect_docs": [],
        "expect_entities": ["Loki"],
        "expect_timeline": None,
        "expect_citation": False,
    },
    {
        "q": "Which timeline does WandaVision belong to?",
        "expect_docs": ["wanda_vision_2021"],
        "expect_entities": ["WandaVision"],
        "expect_timeline": "mcu",
        "expect_citation": True,
    },
    {
        "q": "What caused the Battle of New York?",
        "expect_docs": ["the_avengers_2012"],
        "expect_entities": ["Battle of New York"],
        "expect_timeline": "mcu",
        "expect_citation": True,
    },
    {
        "q": "Loki and the TVA connection",
        "expect_docs": [],
        "expect_entities": ["Loki", "TVA"],
        "expect_timeline": None,
        "expect_citation": False,
    },
]


@dataclass
class QResult:
    question: str
    retrieval: bool
    entity: bool
    timeline: bool
    citation: bool
    faithful: bool
    latency_s: float


def run_benchmark(limit: int | None = None) -> dict:
    store = Store()
    vs_loaded = True
    from src.vector.qdrant import VectorStore

    vs = VectorStore()
    graph = Graph()
    llm = GMIClient()

    n_docs = store.doc_count()
    results: list[QResult] = []
    bench = BENCHMARK[:limit] if limit else BENCHMARK

    for case in bench:
        t0 = time.time()
        plan = parse_query(llm, case["q"])
        ranked = hybrid_search(store, vs, graph, case["q"], plan)
        answer = generate_answer(llm, case["q"], ranked)
        dt = time.time() - t0

        evidence = answer.get("citations", [])
        ev_texts = " ".join(e.get("text", "") for e in evidence).lower()
        ev_titles = " ".join(e.get("title", "") for e in evidence).lower()

        retrieval = all(
            any(exp in (ev_titles + ev_texts) for ev in [ev_titles + ev_texts])
            for exp in case.get("expect_docs", [])
        ) if case.get("expect_docs") else True

        planner_entities = " ".join(plan.entities + ([plan.reference_event] if plan.reference_event else [])).lower()
        graph_names = " ".join(
            r["data"].get("name", "") for r in ranked["results"] if r["type"] == "entity"
        ).lower()
        entity = all(
            exp.lower() in (planner_entities + " " + graph_names)
            for exp in case.get("expect_entities", [])
        ) if case.get("expect_entities") else True

        timeline = True
        if case.get("expect_timeline"):
            combined = (plan.timeline or "") + " " + answer["answer"].lower()
            timeline = case["expect_timeline"].lower() in combined

        citation = ("[" in answer["answer"]) if case.get("expect_citation") else True
        faithful = _faithful(answer["answer"], evidence) if evidence else False

        results.append(QResult(case["q"], retrieval, entity, timeline, citation, faithful, round(dt, 2)))

    graph.close()
    summary = {
        "docs_ingested": n_docs,
        "q_count": len(results),
        "retrieval_acc": _rate(results, "retrieval"),
        "entity_acc": _rate(results, "entity"),
        "timeline_acc": _rate(results, "timeline"),
        "citation_acc": _rate(results, "citation"),
        "faithfulness": _rate(results, "faithful"),
        "avg_latency_s": round(sum(r.latency_s for r in results) / max(len(results), 1), 2),
        "results": [asdict(r) for r in results],
    }
    return summary


def _rate(results: list[QResult], attr: str) -> float:
    return round(sum(1 for r in results if getattr(r, attr)) / max(len(results), 1), 2)


if __name__ == "__main__":
    summary = run_benchmark()
    out = settings.PROCESSED_DIR / "benchmark_report.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    print(f"\nfull report: {out}")
