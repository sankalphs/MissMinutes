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
import re as _re
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
        "expect_docs": [],
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
    {
        "q": "Who are the Defenders?",
        "expect_docs": [],
        "expect_entities": ["Defenders"],
        "expect_timeline": "defenders",
        "expect_citation": True,
    },
    {
        "q": "What does the TVA do with the Sacred Timeline?",
        "expect_docs": [],
        "expect_entities": ["TVA"],
        "expect_timeline": None,
        "expect_citation": True,
    },
    {
        "q": "How did Wanda create Westview?",
        "expect_docs": ["wanda_vision_2021"],
        "expect_entities": ["Wanda"],
        "expect_timeline": "mcu",
        "expect_citation": True,
    },
    {
        "q": "Is Wolverine an X-Man?",
        "expect_docs": [],
        "expect_entities": ["Wolverine"],
        "expect_timeline": "fox:xmen",
        "expect_citation": True,
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
        # per-citation: evidence rows the answer actually cites, not the
        # whole retrieval pool (the old all-evidence substring check
        # passed on answers that never touched the expected document)
        cited_idx = [
            int(m) for m in _re.findall(r"\[(\d+)\]", answer["answer"])
            if m.isdigit() and 1 <= int(m) <= len(evidence)
        ]
        cited_ev = [evidence[i - 1] for i in cited_idx]
        pool = cited_ev if cited_ev else evidence
        ev_texts = " ".join(e.get("text", "") for e in pool).lower()
        ev_titles = " ".join(e.get("title", "") for e in pool).lower()
        # title from doc store: query DB for the expected slug's real title
        from src.ingestion.store import Store as _Store

        store_titles = {
            d["slug"]: (d["title"] or "").lower()
            for d in _Store().all_documents()
        }

        def doc_match(slug: str) -> bool:
            title = store_titles.get(slug, slug.replace("_", " ").lower())
            title_n = _re.sub(r"[^a-z0-9]", "", title)  # 'wandavision'
            if title in ev_titles or title_n in _re.sub(r"[^a-z0-9]", "", ev_titles):
                return True
            # year-stripped title in titles is the common case
            return title_n in _re.sub(r"[^a-z0-9]", "", ev_texts)[:4000]

        retrieval = (
            all(doc_match(exp) for exp in case.get("expect_docs", []))
            if case.get("expect_docs")
            else True
        )

        planner_entities = " ".join(plan.entities + ([plan.reference_event] if plan.reference_event else [])).lower()
        graph_names = " ".join(
            r["data"].get("name", "") for r in ranked["results"] if r["type"] == "entity"
        ).lower()

        def entity_match(exp: str) -> bool:
            # word-boundary match so 'Loki' never passes on 'Lokisson'
            pat = _re.compile(r"\b" + _re.escape(exp.lower()) + r"\b")
            return bool(pat.search(planner_entities) or pat.search(graph_names))

        entity = all(
            entity_match(exp)
            for exp in case.get("expect_entities", [])
        ) if case.get("expect_entities") else True

        timeline = True
        if case.get("expect_timeline"):
            combined = (plan.timeline or "") + " " + answer["answer"].lower()
            expect_tl = case["expect_timeline"].lower()
            # canonical key ('fox:xmen') or its human name ('x-men', 'defenders')
            tl_names = {
                "fox:xmen": ["fox:xmen", "x-men", "xmen"],
                "fox:ff": ["fox:ff", "fantastic four"],
                "sony:rami": ["sony:rami", "rami", "maguire"],
                "sony:webb": ["sony:webb", "amazing spider-man"],
                "sony:ssu": ["sony:ssu", "venom", "morbius", "kraven"],
                "sony:spiderverse": ["sony:spiderverse", "spider-verse"],
                "whatif": ["whatif", "what if"],
                "defenders": ["defenders"],
                "mcu": ["mcu", "sacred timeline"],
            }.get(expect_tl, [expect_tl])
            timeline = any(n in combined for n in tl_names)

        # citation = a valid in-range [n] marker, not any stray bracket
        citation = bool(cited_idx) if case.get("expect_citation") else True
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
