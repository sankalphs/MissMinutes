from src.search.synthesis import (
    _faithful,
    _parse_answer_block,
    build_evidence_context,
    generate_answer,
)
from src.llm.client import GMIClient

EVIDENCE = [
    {"chunk_id": "doc:the_avengers_2012#s0001c0042", "text": "Loki escapes with the Tesseract during the Battle of New York in 2012.", "title": "The Avengers"},
    {"chunk_id": "doc:loki_2021_s01e01#s0000c0001", "text": "The Time Variance Authority captures Loki for violating the sacred timeline.", "title": "Loki S01E01"},
]


def test_build_evidence_context_mixes_types() -> None:
    ranked = {
        "results": [
            {"type": "entity", "data": {"id": "character:loki", "name": "Loki", "label": "Character", "neighbors": [{"name": "TVA", "id": "x"}]}},
            {"type": "chunk", "data": {"chunk_id": "doc:a#s0000c00001", "text": "alpha", "title": "A"}},
            {"type": "chunk", "data": {"chunk_id": "doc:a#s0000c00001", "text": "alpha", "title": "A"}},
            {"type": "path", "data": {"path": ["Loki", "capture", "TVA"]}},
        ]
    }
    text, ev = build_evidence_context(ranked["results"])
    assert "[1]" in text and "[GRAPH]" in text and "[GRAPH PATH]" in text
    assert len(ev) == 3


def test_parse_answer_block() -> None:
    raw = "ANSWER: Loki stole the Tesseract in 2012. [1]\n\nUNCERTAINTY: none\n\nSOURCES: The Avengers, Loki S01E01"
    out = _parse_answer_block(raw, EVIDENCE)
    assert "Tesseract" in out["answer"]
    assert out["uncertainty"] == "none"
    assert "The Avengers" in out["sources"]


def test_faithful_gate() -> None:
    good = "Loki escapes with the Tesseract during the Battle of New York. [1]"
    no_cite = "Loki escapes with the Tesseract during the Battle of New York."
    out_of_range = "Loki escapes with the Tesseract. [7]"
    assert _faithful(good, EVIDENCE)
    assert not _faithful(no_cite, EVIDENCE)
    assert not _faithful(out_of_range, EVIDENCE)


def test_generate_answer_live() -> None:
    ranked = {
        "results": [
            {"type": "chunk", "data": EVIDENCE[0], "score": 0.5},
            {"type": "chunk", "data": EVIDENCE[1], "score": 0.4},
        ]
    }
    out = generate_answer(
        GMIClient(), "What happened after Loki escaped with the Tesseract?", ranked
    )
    assert "Tesseract" in out["answer"] or out["uncertainty"] != "none"
    assert out["citations"]  # evidence list always attached
    print("ANSWER:", out["answer"][:200])
    print("SOURCES:", out["sources"])
