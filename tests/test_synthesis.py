import pytest

from src.config import settings
from src.llm.client import GMIError, GMIClient
from src.search.synthesis import (
    EVIDENCE_LIMIT,
    _faithful,
    _parse_answer_block,
    _unfaithful_sentences,
    build_evidence_context,
    generate_answer,
)

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


def test_evidence_capped_at_rendered_slots() -> None:
    """A5: the LLM may only cite slots the annex renders — 12-seen vs
    6-rendered broke the citation promise."""
    ranked = {"results": [
        {"type": "chunk", "data": {"chunk_id": f"doc:a#{i:03d}", "text": f"text {i}", "title": "A"}}
        for i in range(20)
    ]}
    text, ev = build_evidence_context(ranked["results"])
    assert len(ev) == EVIDENCE_LIMIT
    assert f"[{EVIDENCE_LIMIT}]" in text
    assert f"[{EVIDENCE_LIMIT + 1}]" not in text


def test_parse_answer_block() -> None:
    raw = "ANSWER: Loki stole the Tesseract in 2012. [1]\n\nUNCERTAINTY: none\n\nSOURCES: The Avengers, Loki S01E01"
    out = _parse_answer_block(raw, EVIDENCE)
    assert "Tesseract" in out["answer"]
    assert out["uncertainty"] == "none"
    assert "The Avengers" in out["sources"]


def test_faithful_gate_passes_supported_claims() -> None:
    good = "Loki escapes with the Tesseract during the Battle of New York. [1]"
    assert _faithful(good, EVIDENCE)


def test_faithful_gate_rejects_uncited_claims() -> None:
    """B4: an uncited factual sentence used to slip through the global
    word-overlap check."""
    uncited_second = (
        "Loki escapes with the Tesseract during the Battle of New York. [1] "
        "He later conquered Asgard and ruled the Nine Realms as king."
    )
    assert not _faithful(uncited_second, EVIDENCE)


def test_faithful_gate_rejects_wrong_chunk_support() -> None:
    """B4: citing a passage that does not support the sentence fails even
    with plausible global overlap."""
    wrong_support = (
        "Wanda created the Westview anomaly to trap an entire town. [1]"
    )
    assert not _faithful(wrong_support, EVIDENCE)


def test_faithful_gate_allows_hedges() -> None:
    hedged = "The evidence retrieved does not specify what happened next. [1]"
    assert _faithful(hedged, EVIDENCE)


def test_faithful_gate_allows_evidence_structure_claims() -> None:
    """The insufficiency pattern the model legitimately produces when
    evidence doesn't answer the question — meta-sentences about what the
    evidence contains must pass; only world-claims need chunk support."""
    answer = (
        "Based on the provided evidence, WandaVision's specific timeline affiliation is not directly stated. "
        "The show itself is referenced in entries [1], [2], [3], and [4], but none of these explicitly place "
        "it within the Sacred Timeline or any other specific timeline. "
        "Evidence [5] and [6] discuss the Sacred Timeline, but do not mention WandaVision. "
        "Therefore, I cannot determine from this evidence alone which timeline WandaVision belongs to [1][2][3][4][5][6]."
    )
    assert _faithful(answer, EVIDENCE * 3)


def test_inline_citations_do_not_split_sentences() -> None:
    answer = "Evidence [1] and [2] discuss the Sacred Timeline. [1] Loki escaped. [2]"
    bad = _unfaithful_sentences(answer, EVIDENCE)
    # "Loki escaped. [2]" has support; the meta sentence passes — none bad
    assert bad == []


def test_faithful_gate_rejects_missing_or_out_of_range_cites() -> None:
    no_cite = "Loki escapes with the Tesseract during the Battle of New York."
    out_of_range = "Loki escapes with the Tesseract. [7]"
    assert not _faithful(no_cite, EVIDENCE)
    assert not _faithful(out_of_range, EVIDENCE)


def test_unfaithful_sentences_names_the_offender() -> None:
    answer = (
        "Loki escapes with the Tesseract during the Battle of New York. [1] "
        "He ruled Asgard for a thousand glorious winters."
    )
    bad = _unfaithful_sentences(answer, EVIDENCE)
    assert len(bad) == 1
    assert "Asgard" in bad[0]


def test_faithful_gate_rejects_meta_noun_smuggling() -> None:
    """A cited world-claim must not buy hedge exemption just by containing
    the word 'evidence'/'sources' — exemption needs a reporting cue."""
    smuggled = "He hid the evidence inside a vault underneath the archive. [1]"
    assert not _faithful(smuggled, EVIDENCE)


class _FirstAnswerThenRaise:
    """First chat returns an unfaithful answer; the regen call dies."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, **kw):
        self.calls += 1
        if self.calls == 1:
            return ("ANSWER: He ruled Asgard for a thousand glorious winters. [1]\n"
                    "UNCERTAINTY: none\nSOURCES: The Avengers")
        raise GMIError("regen backend down")


def test_regeneration_failure_keeps_first_answer() -> None:
    """A dead regen call must not destroy a good first answer."""
    ranked = {"results": [{"type": "chunk", "data": EVIDENCE[0], "score": 0.5}]}
    out = generate_answer(_FirstAnswerThenRaise(), "Who ruled Asgard?", ranked)
    assert "Asgard" in out["answer"]
    assert "could not be re-verified" in out["uncertainty"]
    assert out["citations"]


@pytest.mark.skipif(not settings.GMI_API_KEY, reason="needs live GMI key (.env)")
@pytest.mark.live
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
    # sources must be grounded in evidence titles (B10)
    assert all(s in {e["title"] for e in out["citations"]} for s in out["sources"])
    print("ANSWER:", out["answer"][:200])
    print("SOURCES:", out["sources"])
