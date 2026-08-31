"""UI-layer tests — app.py's orchestration, status vocabulary, evidence
rendering and scope bridges, all hermetic (no backends, no LLM)."""
import re

import gradio as gr
import pytest

import app
from app import (
    _answer_html,
    _ev_row,
    _status_html,
    _used_legs,
    echo_scope,
    scope_from_scene,
    search_and_answer,
)
from src.search.planner import QueryPlan


# --- evidence badges come from the payload, never the title (A4) ------------

def test_ev_row_badge_uses_timeline_id_not_title_guess() -> None:
    """Spider-Man: Homecoming is an mcu title — the old title-substring
    heuristic badged it RAMI SPIDER-MAN."""
    row = _ev_row(1, {
        "title": "Spider-Man: Homecoming",
        "timeline_id": "mcu",
        "text": "Peter Parker returns from Germany.",
        "chunk_id": "doc:smh_2017#s0000c00001",
    })
    assert "SACRED TIMELINE" in row
    assert "RAMI SPIDER-MAN" not in row
    assert "data-timeline='mcu'" in row


def test_ev_row_badge_deadpool_wolverine_is_mcu() -> None:
    row = _ev_row(2, {
        "title": "Deadpool & Wolverine",
        "timeline_id": "mcu",
        "text": "Wade digs up Logan's bones.",
        "chunk_id": "doc:dpw_2024#s0000c00003",
    })
    assert "SACRED TIMELINE" in row
    assert "FOX X-MEN" not in row


def test_ev_row_badge_fox_xmen_from_payload() -> None:
    row = _ev_row(3, {
        "title": "X-Men",
        "timeline_id": "fox:xmen",
        "text": "Mutants register with the government.",
        "chunk_id": "doc:xm_2000#s0000c00001",
    })
    assert "FOX X-MEN" in row
    assert "data-timeline='fox:xmen'" in row


def test_ev_row_graph_rows_badge_knowledge_graph() -> None:
    """Graph evidence rows carry no timeline_id — they badge KNOWLEDGE
    GRAPH and light no branch (the old fallback badged them mcu)."""
    row = _ev_row(4, {
        "title": "knowledge graph",
        "text": "[GRAPH] Character: Loki — relates to: Thor",
        "chunk_id": "graph:character:loki",
    })
    assert "KNOWLEDGE GRAPH" in row
    assert "data-timeline" not in row


def test_ev_row_ellipsis_only_when_truncated() -> None:
    short = _ev_row(1, {"title": "A", "timeline_id": "mcu", "text": "short quote", "chunk_id": "x"})
    long_text = {"title": "A", "timeline_id": "mcu",
                 "text": "word " * 100, "chunk_id": "x"}
    long_row = _ev_row(2, long_text)
    assert "&hellip;" not in short
    assert "&hellip;" in long_row


def test_ev_rows_are_anchor_targets() -> None:
    row = _ev_row(7, {"title": "A", "timeline_id": "mcu", "text": "t", "chunk_id": "x"})
    assert "id='ev-07'" in row


# --- status line: tri-state legs, used legs, honest vocabulary (A6/C10) ----

def test_status_all_legs_served() -> None:
    html = _status_html(
        {"graph": "ok", "vector": "ok", "lexical": "ok"}, ["graph", "vector", "lexical"], 12.0
    )
    assert "FILE PROCESSED" in html
    assert "GRAPH · VECTOR · LEXICAL" in html
    assert "UNREACHABLE" not in html
    assert "NO FILES" not in html


def test_status_names_dead_leg_not_empty_one() -> None:
    """A6: a healthy graph with no entity match used to print
    GRAPH UNREACHABLE."""
    html = _status_html(
        {"graph": "empty", "vector": "ok", "lexical": "ok"}, ["vector"], 42.2
    )
    assert "FILE PROCESSED — GRAPH (NO FILES) · VECTOR · LEXICAL (NO FILES)" in html
    assert "UNREACHABLE" not in html


def test_status_reports_down_legs() -> None:
    html = _status_html(
        {"graph": "down", "vector": "ok", "lexical": "ok"}, ["vector", "lexical"], 42.2
    )
    assert "DEGRADED" in html
    assert "GRAPH UNREACHABLE" in html
    assert "VECTOR · LEXICAL" in html


def test_status_lexical_down_is_reportable() -> None:
    """A1+A6: the lexical leg dying on worker threads was unreportable."""
    html = _status_html(
        {"graph": "ok", "vector": "ok", "lexical": "down"}, ["graph", "vector"], 3.1
    )
    assert "LEXICAL UNREACHABLE" in html


def test_status_all_dark() -> None:
    html = _status_html(
        {"graph": "down", "vector": "down", "lexical": "down"}, [], 3.1
    )
    assert "NO BACKENDS REACHABLE" in html


def test_status_no_evidence_on_branch() -> None:
    html = _status_html(
        {"graph": "empty", "vector": "empty", "lexical": "empty"}, [], 12.0
    )
    assert "NO EVIDENCE ON THIS BRANCH" in html


# --- used-legs attribution (C10) --------------------------------------------

def _ranked(rows):
    return {"results": rows, "legs": {"graph": "ok", "vector": "ok", "lexical": "ok"}}


def test_used_legs_follow_citations_not_service() -> None:
    rows = [
        {"type": "entity", "data": {"id": "character:loki"}},
        {"type": "chunk", "data": {"chunk_id": "a"}},
        {"type": "chunk", "data": {"chunk_id": "b", "source": "fts"}},
    ]
    used = _used_legs(_ranked(rows), "The ruling is issued. [2] And cited. [3]")
    assert used == ["vector", "lexical"]


def test_used_legs_graph_only_when_graph_cited() -> None:
    rows = [
        {"type": "entity", "data": {"id": "character:loki"}},
        {"type": "chunk", "data": {"chunk_id": "a"}},
    ]
    used = _used_legs(_ranked(rows), "Grounded only. [2]")
    assert "graph" not in used


def test_used_legs_fallback_when_no_citations() -> None:
    rows = [
        {"type": "entity", "data": {"id": "character:loki"}},
        {"type": "chunk", "data": {"chunk_id": "a"}},
    ]
    used = _used_legs(_ranked(rows), "No markers at all.")
    assert used  # names whatever served rows


# --- answer rendering (B7) ---------------------------------------------------

def test_answer_html_links_in_range_citations() -> None:
    out = _answer_html("Loki escapes with the Tesseract. [1] Out of range. [9]")
    assert "<a class='cite' href='#ev-01'" in out
    assert "[9]" in out and "href='#ev-09'" not in out


def test_answer_html_escapes_but_keeps_cites() -> None:
    out = _answer_html("<script>alert('x')</script> escaped. [1]")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# --- scope bridges (A3) ------------------------------------------------------

def test_scope_from_scene_maps_keys() -> None:
    assert scope_from_scene("fox:xmen") == "FOX X-MEN"
    assert scope_from_scene("") == "All timelines"
    assert scope_from_scene("unknown-key") == "All timelines"


def test_echo_scope_carries_label_for_js_bridge() -> None:
    out = echo_scope("FOX X-MEN")
    assert "FOX X-MEN" in out
    assert "id='scope-echo'" in out
    out_all = echo_scope("All timelines")
    assert "ALL TIMELINES" in out_all


# --- empty + error paths (A7/C7/C8) -----------------------------------------

def test_empty_query_is_a_noop() -> None:
    a, e, s = search_and_answer("", "All timelines")
    for part in (a, e, s):
        assert isinstance(part, dict) and "value" not in part and "update" not in part


def test_pipeline_error_keeps_status_line_and_world_voice() -> None:
    """A7/C8: errors used to blank the status and leak GMIError class names."""
    def boom(*a, **k):
        raise RuntimeError("GMIError: backend exploded")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app, "get_store", lambda: object())
    monkeypatch.setattr(app, "get_vector", lambda: object())
    monkeypatch.setattr(app, "get_graph", lambda: object())
    monkeypatch.setattr(app, "get_llm", lambda: object())
    monkeypatch.setattr(app, "parse_query", boom)
    try:
        answer, evidence, status = search_and_answer("Who is Loki?", "All timelines")
    finally:
        monkeypatch.undo()

    assert "REQUEST REJECTED" in answer
    assert "GMIError" not in answer, "error copy leaked the exception class"
    assert "pipeline-status" in status and "FILE REJECTED" in status
    assert "No passages accompany a rejected request" in evidence


# --- hermetic end-to-end (search_and_answer with fakes) ---------------------

class _FakeStore:
    def fts_search(self, q, limit=20, timeline=None):
        return [{
            "chunk_id": "doc:loki#s1", "document_id": "doc:loki",
            "text": "The Time Variance Authority captures Loki.",
            "title": "Loki", "timeline_id": "mcu", "source": "fts",
        }]


class _FakeVS:
    def search(self, vec, limit=10, timeline=None):
        return [{
            "chunk_id": "doc:avengers#s1", "document_id": "doc:avengers",
            "text": "Loki escapes with the Tesseract during the Battle of New York.",
            "title": "The Avengers", "timeline_id": "mcu",
        }]


class _FakeGraph:
    def session(self):
        raise RuntimeError("aura unreachable")


class _FakePlanLLM:
    def chat_json(self, *a, **k):
        return {"entities": ["Loki"], "operation": "find_entity"}


def test_search_and_answer_renders_full_pipeline(monkeypatch):
    monkeypatch.setattr(app, "get_store", _FakeStore)
    monkeypatch.setattr(app, "get_vector", _FakeVS)
    monkeypatch.setattr(app, "get_graph", _FakeGraph)
    monkeypatch.setattr(app, "get_llm", _FakePlanLLM)
    monkeypatch.setattr(app, "parse_query", lambda llm, q: QueryPlan(entities=["Loki"]))
    monkeypatch.setattr(app, "generate_answer", lambda llm, q, ranked: {
        "answer": "Loki escapes with the Tesseract during the Battle of New York. [1]",
        "uncertainty": "none",
        "sources": ["The Avengers"],
        "citations": ranked["results"][0]["data"] and [
            ranked["results"][0]["data"],
            {"chunk_id": "doc:loki#s1", "text": "The TVA captures Loki.",
             "title": "Loki", "timeline_id": "mcu"},
        ],
    })

    answer, evidence, status = app.search_and_answer(
        "What happened after Loki escaped with the Tesseract?", "All timelines"
    )

    assert "RULING ISSUED" in answer
    assert "href='#ev-01'" in answer
    assert "SACRED TIMELINE" in evidence  # badge from payload
    assert "id='ev-01'" in evidence and "id='ev-02'" in evidence
    assert "FILE PROCESSED" in status
    assert "GRAPH UNREACHABLE" in status  # fake aura is down: reported


def test_search_and_answer_scoped_passes_timeline_to_hybrid(monkeypatch):
    seen = {}

    def fake_hybrid(store, vs, graph, q, plan):
        seen["timeline"] = plan.timeline
        return {
            "results": [
                {"type": "chunk", "data": {
                    "chunk_id": "doc:venom#s1", "text": "We are Venom.",
                    "title": "Venom", "timeline_id": "sony:ssu", "source": "fts",
                }},
            ],
            "legs": {"graph": "empty", "vector": "ok", "lexical": "ok"},
        }

    monkeypatch.setattr(app, "get_store", _FakeStore)
    monkeypatch.setattr(app, "get_vector", _FakeVS)
    monkeypatch.setattr(app, "get_graph", _FakeGraph)
    monkeypatch.setattr(app, "get_llm", _FakePlanLLM)
    monkeypatch.setattr(app, "parse_query", lambda llm, q: QueryPlan(entities=["Venom"]))
    monkeypatch.setattr(app, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(app, "generate_answer", lambda llm, q, ranked: {
        "answer": "We are Venom. [1]", "uncertainty": "none",
        "sources": ["Venom"], "citations": ranked["results"][0]["data"] and [
            ranked["results"][0]["data"]],
    })

    answer, evidence, status = app.search_and_answer(
        "Who is Venom?", "VENOM · MORBIUS · KRAVEN · SPIDER-VERSE"
    )
    assert seen["timeline"] == "sony:ssu"
    assert "SONY UNIVERSE" in evidence
