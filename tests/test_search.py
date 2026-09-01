import pytest

from src.config import settings
from src.llm.client import GMIClient
from src.search.hybrid import hybrid_search, lexical_search, rerank, semantic_search
from src.search.planner import QueryPlan, parse_query


def _gmi_key() -> bool:
    return bool(settings.GMI_API_KEY)


def _fake_llm_returning(plan: dict) -> GMIClient:
    class FakeLLM(GMIClient):
        def __init__(self):  # no real calls allowed
            self.calls = 0

        def chat_json(self, *a, **k):  # planner path
            self.calls += 1
            return plan

        def chat(self, *a, **k):  # pragma: no cover
            raise AssertionError("planner tests must not hit the answer LLM")

    return FakeLLM()


def test_simple_query_skips_llm() -> None:
    llm = _fake_llm_returning({"entities": ["WRONG"]})

    plan = parse_query(llm, "Loki")
    assert plan.operation == "find_entity"
    assert plan.entities == ["Loki"]
    assert llm.calls == 0


def test_question_shapes_never_take_the_fast_path() -> None:
    """B1: 'Who is Loki' etc. used to capture the whole sentence as an
    entity, corrupting every leg downstream. They must reach the LLM."""
    llm = _fake_llm_returning({"entities": ["Loki"], "operation": "find_entity"})

    for q in (
        "Who is Loki",
        "What is the TVA",
        "Who is Thor",
        "What happened to Wanda",
        "Tell me about Mobius",
        "Where is Asgard",
    ):
        plan = parse_query(llm, q)
        assert plan.entities != [q], f"{q!r} was captured verbatim as an entity"
        assert llm.calls > 0, f"{q!r} never reached the planner LLM"
        llm.calls = 0


def test_timeline_enum_enforced() -> None:
    with pytest.raises(Exception):
        QueryPlan(entities=["x"], timeline="marvel")


def test_invalid_plan_fields_are_coerced_not_discarded() -> None:
    """One over-long or out-of-enum field must not throw away the whole
    (valid) plan — entities truncate to 6, bad literals fall to defaults."""
    llm = _fake_llm_returning({
        "entities": ["a", "b", "c", "d", "e", "f", "g"],
        "operation": "bogus",
        "intent": "weird",
        "timeline": "marvel",
        "reference_event": "X" * 300,
    })
    plan = parse_query(llm, "What happened to Wanda?")
    assert plan.entities == ["a", "b", "c", "d", "e", "f"]
    assert plan.operation == "free_search"
    assert plan.intent == "semantic"
    assert plan.timeline is None
    assert len(plan.reference_event) == 160


def test_rerank_grounds_chunks_over_synthetic_graph_rows(monkeypatch) -> None:
    """B3: graph entity rows are neighbor-name summaries, not passages —
    they must not outrank grounded subtitle chunks."""
    # the reranker is heavy (torch) — unit tests inject flat scores
    monkeypatch.setattr(
        "src.search.rerank.cross_encoder_scores",
        lambda query, texts, model_name=None: [0.9] * len(texts),
    )
    plan = QueryPlan(entities=["Loki"], operation="find_entity")
    sem = [
        {"chunk_id": "doc:x#s0000c00001", "text": "loki text", "score": 0.9},
        {"chunk_id": "doc:x#s0000c00002", "text": "other", "score": 0.8},
    ]
    lex = [
        {"chunk_id": "doc:x#s0000c00001", "text": "loki text", "source": "fts"},
    ]
    graph_hits = [{"id": "character:loki", "name": "Loki", "label": "Character", "neighbors": []}]
    out = rerank(plan, "Loki", lex, sem, graph_hits)

    chunks = [r for r in out["results"] if r["type"] == "chunk"]
    entities = [r for r in out["results"] if r["type"] == "entity"]
    assert chunks and entities
    # the dual-leg chunk (lexical + vector) outranks the synthetic entity row
    assert chunks[0]["data"]["chunk_id"] == "doc:x#s0000c00001"
    assert chunks[0]["score"] > entities[0]["score"]
    assert 0.0 <= chunks[0]["score"] <= 1.0


def test_rerank_path_results_top() -> None:
    plan = QueryPlan(entities=["Loki", "TVA"], operation="find_connection")
    out = rerank(
        plan, "Loki and TVA", [], [],
        [{"path": ["Loki", "TVA capture", "Mobius"]}],
    )
    assert out["results"][0]["type"] == "path"
    assert out["results"][0]["score"] >= 0.9


def _fake_store(hits=None, fail=False):
    class FakeStore:
        def fts_search(self, query, limit=20, timeline=None, rank=False, raw=False):
            if fail:
                raise RuntimeError("lexical store down")
            return hits if hits is not None else []
    return FakeStore()


def _fake_vs(hits=None, fail=False):
    class FakeVS:
        def search(self, vector, limit=10, timeline=None):
            if fail:
                raise RuntimeError("qdrant down")
            return hits if hits is not None else []
    return FakeVS()


class _FakeGraph:
    def session(self):
        raise RuntimeError("aura down")


def test_legs_report_down_vs_empty() -> None:
    """A6: a healthy backend with no matches is NOT the same as a dead one."""
    plan = QueryPlan(entities=["Loki"], operation="find_entity")

    ranked = hybrid_search(_fake_store(), _fake_vs(), _FakeGraph(), "Loki", plan)
    assert ranked["legs"] == {"graph": "down", "vector": "empty", "lexical": "empty"}

    hits = [{"chunk_id": "doc:x#s1", "text": "loki", "timeline_id": "mcu", "title": "Loki"}]
    ranked = hybrid_search(_fake_store(hits), _fake_vs(hits), _FakeGraph(), "Loki", plan)
    assert ranked["legs"] == {"graph": "down", "vector": "ok", "lexical": "ok"}


def test_lexical_scope_passed_through() -> None:
    """A2: plan.timeline must reach the FTS layer."""
    seen = {}

    class SpyStore:
        def fts_search(self, query, limit=20, timeline=None, rank=False, raw=False):
            seen["timeline"] = timeline
            return []

    plan = QueryPlan(entities=["Loki"], timeline="fox:xmen")
    lexical_search(SpyStore(), plan, "Loki")
    assert seen["timeline"] == "fox:xmen"


def test_semantic_scope_has_no_unscoped_fallback() -> None:
    """A2: a scoped search that comes back empty stays empty — the old
    code silently re-searched across every timeline."""
    calls = []

    class ScopeVS:
        def search(self, vector, limit=10, timeline=None):
            calls.append(timeline)
            return []

    import src.search.hybrid as hybrid_mod

    orig = hybrid_mod.embed_query
    hybrid_mod.embed_query = lambda q: [0.0]
    try:
        plan = QueryPlan(entities=["Wolverine"], timeline="sony:rami")
        hits, state = semantic_search(ScopeVS(), plan, "Wolverine")
    finally:
        hybrid_mod.embed_query = orig

    assert calls == ["sony:rami"], "scoped semantic search fell back to unscoped"
    assert hits == [] and state == "empty"


@pytest.mark.skipif(not _gmi_key(), reason="needs live GMI key (.env)")
@pytest.mark.live
def test_complex_query_plan_parses_live() -> None:
    plan = parse_query(GMIClient(), "What happened after Loki escaped with the Tesseract?")
    assert plan.reference_event or plan.entities, f"plan empty: {plan}"
    assert plan.operation in ("next_events", "find_events", "free_search")
    # the fast-path must not have swallowed the question whole
    assert plan.entities != ["What happened after Loki escaped with the Tesseract?"]
