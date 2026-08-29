from pathlib import Path

import pytest

from src.search.hybrid import rerank
from src.search.planner import QueryPlan, parse_query
from src.llm.client import GMIClient


def test_simple_query_skips_llm() -> None:
    class FakeLLM(GMIClient):
        def __init__(self):  # no real calls allowed
            pass

        def chat(self, *a, **k):  # pragma: no cover
            raise AssertionError("simple query must not hit LLM")

    plan = parse_query(FakeLLM(), "Loki")
    assert plan.operation == "find_entity"
    assert plan.entities == ["Loki"]


def test_complex_query_plan_parses_live() -> None:
    plan = parse_query(GMIClient(), "What happened after Loki escaped with the Tesseract?")
    assert plan.reference_event or plan.entities, f"plan empty: {plan}"
    assert plan.operation in ("next_events", "find_events", "free_search")


def test_timeline_enum_enforced() -> None:
    with pytest.raises(Exception):
        QueryPlan(entities=["x"], timeline="marvel")


def test_rerank_prefers_graph_over_semantic() -> None:
    plan = QueryPlan(entities=["Loki"], operation="find_entity")
    sem = [
        {"chunk_id": "doc:x#s0000c00001", "text": "loki text", "score": 0.9},
        {"chunk_id": "doc:x#s0000c00002", "text": "other", "score": 0.8},
    ]
    lex = [
        {"chunk_id": "doc:x#s0000c00001", "text": "loki text"},
    ]
    graph_hits = [{"id": "character:loki", "name": "Loki", "label": "Character", "neighbors": []}]
    out = rerank(plan, "Loki", lex, sem, graph_hits)
    assert out["results"][0]["type"] == "entity"
    assert out["results"][0]["data"]["name"] == "Loki"
    # chunk that appears in both lex and sem should be boosted but stay below graph
    chunks = [r for r in out["results"] if r["type"] == "chunk"]
    assert chunks and chunks[0]["data"]["chunk_id"] == "doc:x#s0000c00001"
    assert 0.4 <= chunks[0]["score"] < 0.9


def test_rerank_path_results_top() -> None:
    plan = QueryPlan(entities=["Loki", "TVA"], operation="find_connection")
    out = rerank(
        plan, "Loki and TVA", [], [],
        [{"path": ["Loki", "TVA capture", "Mobius"]}],
    )
    assert out["results"][0]["type"] == "path"
    assert out["results"][0]["score"] == 1.0
