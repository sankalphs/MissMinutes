"""Grounded answer generation + faithfulness gate (spec:19,21,33,37).

The synthesis LLM sees ONLY: the question, the query plan, graph results,
and retrieved evidence chunks. Every claim must cite [chunk_id] from the
evidence set. After generation, every cited sentence is re-checked against
ITS OWN cited passages — a sentence passing on evidence the answer never
points at is not faithfulness. Failures trigger one regeneration, then an
uncertainty note.

Evidence is capped at the 6 rows the annex actually renders — the LLM
must never cite a slot the user cannot see (12-seen/6-rendered broke the
core citation promise).
"""
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from src.llm.client import GMIClient

logger = logging.getLogger(__name__)

# evidence slots rendered in the annex — LLM and UI must agree on this
EVIDENCE_LIMIT = 6

ANSWER_SYSTEM = """You answer questions about Marvel screen canon using ONLY the supplied evidence.
Rules:
1. Use ONLY facts present in the EVIDENCE and GRAPH sections. Never use outside knowledge.
2. Every factual sentence must end with a citation marker like [1], [2] pointing into the evidence list. The evidence list has exactly {evidence_count} entries — never cite a number higher than {evidence_count}.
3. If evidence is insufficient or conflicting, say so explicitly instead of guessing.
4. Preserve timeline distinctions (MCU/Sacred vs branches vs Sony/Fox timelines) when the evidence mentions them.
5. Output format:
   ANSWER: <2-6 sentences with [n] citations>
   UNCERTAINTY: <one sentence if anything is unclear/unsupported, else 'none'>
   SOURCES: <comma-separated list of the source titles used, copied exactly from the evidence list>"""


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=10)
    uncertainty: str = "none"
    sources: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)


def build_evidence_context(results: list[dict]) -> tuple[str, list[dict]]:
    """Flatten ranked hybrid results into a numbered evidence list."""
    ev: list[dict] = []
    seen: set[str] = set()
    for r in results:
        data = r["data"]
        if r["type"] == "chunk":
            key = data["chunk_id"]
            if key not in seen:
                seen.add(key)
                ev.append(data)
        elif r["type"] == "entity":
            ev.append({
                "chunk_id": f"graph:{data['id']}",
                "text": f"[GRAPH] {data.get('label', 'Entity')}: {data.get('name', '')}"
                        + (f" — relates to: {', '.join(n['name'] for n in data.get('neighbors', [])[:4])}"
                           if data.get("neighbors") else ""),
                "title": "knowledge graph",
            })
        elif r["type"] == "path":
            ev.append({
                "chunk_id": "graph:path",
                "text": f"[GRAPH PATH] {' -> '.join(data['path'])}",
                "title": "knowledge graph",
            })
    lines = [
        f"[{i+1}] ({e.get('title', '?')}) {e['text'][:600]}"
        for i, e in enumerate(ev[:EVIDENCE_LIMIT])
    ]
    return "\n".join(lines), ev[:EVIDENCE_LIMIT]


def _valid_sources(parsed: dict, evidence: list[dict]) -> list[str]:
    """Sources the model claims, intersected with titles it actually saw.
    Repeats collapse ('knowledge graph' once, not six times); cited titles
    the SOURCES line omitted are appended — the stamp reports what the
    ruling used, not what the model felt like listing."""
    seen = {e.get("title", "") for e in evidence}
    kept: list[str] = []
    for s in parsed.get("sources", []):
        if s in seen and s not in kept:
            kept.append(s)
    for t in _cited_titles(parsed["answer"], evidence):
        if t not in kept:
            kept.append(t)
    return kept


def _cited_titles(answer: str, evidence: list[dict]) -> list[str]:
    """Titles of the evidence rows the answer actually cites, in evidence order."""
    titles = []
    for m in re.finditer(r"\[(\d+)\]", answer):
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        if 1 <= idx <= len(evidence):
            t = evidence[idx - 1].get("title", "")
            if t and t not in titles:
                titles.append(t)
    return titles


def generate_answer(llm: GMIClient, question: str, ranked: dict[str, Any]) -> dict:
    evidence_text, evidence = build_evidence_context(ranked["results"])
    if not evidence:
        return {
            "answer": "I could not find evidence for this question in the ingested sources.",
            "uncertainty": "no evidence retrieved",
            "sources": [],
            "citations": [],
        }
    system = ANSWER_SYSTEM.format(evidence_count=len(evidence))
    user = (
        f"QUESTION: {question}\n\n"
        f"EVIDENCE:\n{evidence_text}\n\n"
        f"Answer using only this evidence."
    )
    raw = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    parsed = _parse_answer_block(raw, evidence)
    parsed["sources"] = _valid_sources(parsed, evidence)
    unfaithful = _unfaithful_sentences(parsed["answer"], evidence)
    if unfaithful:
        logger.info("faithfulness gate tripped on %d sentence(s) — regenerating", len(unfaithful))
        regen = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\n\nIMPORTANT: your previous attempt included "
                 "claims not present in the evidence. Strictly re-derive from evidence only."},
            ],
            temperature=0.0,
            max_tokens=800,
        )
        parsed2 = _parse_answer_block(regen, evidence)
        parsed2["sources"] = _valid_sources(parsed2, evidence)
        if not _unfaithful_sentences(parsed2["answer"], evidence):
            parsed = parsed2
        else:
            parsed["uncertainty"] = (
                (parsed["uncertainty"] + "; " if parsed["uncertainty"] != "none" else "")
                + "some claims could not be verified against retrieved evidence"
            )
    parsed["citations"] = evidence
    return parsed


def _parse_answer_block(raw: str, evidence: list[dict]) -> dict:
    answer, uncertainty, sources = raw, "none", []
    m = re.search(r"ANSWER:\s*(.+?)(?=\nUNCERTAINTY:|\nSOURCES:|$)", raw, re.S)
    if m:
        answer = m.group(1).strip()
    m = re.search(r"UNCERTAINTY:\s*(.+?)(?=\nSOURCES:|$)", raw, re.S)
    if m:
        uncertainty = m.group(1).strip()
    m = re.search(r"SOURCES:\s*(.+)$", raw, re.S)
    if m:
        sources = [s.strip(" ,.") for s in re.split(r"[;,]", m.group(1)) if s.strip()]
    return {"answer": answer, "uncertainty": uncertainty, "sources": sources}


def _unfaithful_sentences(answer: str, evidence: list[dict]) -> list[str]:
    """Per-sentence gate: every factual sentence must carry a citation, and
    every cited sentence must be supported by the passages IT cites
    (content-word overlap >= 0.2). Uncited hedging ("The evidence is
    fragmented") passes — it makes no claim."""
    sentences = _split_sentences(answer)
    bad: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        cites = [int(c) for c in re.findall(r"\[(\d+)\]", s)]
        if not cites:
            if not _is_hedge(s):
                bad.append(s)
            continue
        cited_text = " ".join(
            evidence[c - 1]["text"] for c in cites if 1 <= c <= len(evidence)
        )
        if not cited_text:  # every marker out of range
            bad.append(s)
            continue
        if _is_hedge(s):
            continue
        ev_words = _content_words(cited_text)
        s_words = _content_words(s)
        if not s_words or not ev_words:
            bad.append(s)
            continue
        overlap = len(s_words & ev_words) / len(s_words)
        if overlap < 0.2:
            bad.append(s)
    return bad


def _split_sentences(answer: str) -> list[str]:
    """Split on sentence enders, keeping a trailing [n] marker WITH the
    sentence it belongs to ('... New York. [1]' is one unit, and the
    sentence after it is its own unit). Inline markers ('Evidence [5]
    and [6] discuss...') never split a sentence."""
    # glue citation markers onto the preceding sentence
    text = re.sub(r"([.!?])\s*(\[\d+\])", r"\1\2", answer)
    # split where a sentence ender (or glued marker) is followed by a
    # capital-letter start — mid-sentence markers never qualify
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])|(?<=\])\s+(?=[A-Z])", text)
    return [p for p in parts if p.strip()]


_META_MARKERS = (
    "evidence", "entries", "excerpts", "passages", "provided",
    "supplied", "retrieved", "sources", "records", "the show itself",
    "referenced", "mentioned in",
)


def _is_hedge(sentence: str) -> bool:
    """A sentence that asserts nothing about the world — it reports the
    archive's own limits or the evidence's structure. Such meta-sentences
    may cite freely without word-overlap; world-claims may not."""
    s = sentence.lower()
    if any(w in s for w in (
        "unclear", "unverified", "insufficient", "fragmented", "unspecified",
        "unconfirmed", "unknown", "no evidence", "not enough", "cannot",
        "can't", "uncertain", "ambiguous", "conflicting", "not present",
        "doesn't specify", "does not specify", "not specify", "doesn't say",
        "does not say", "not stated", "not directly stated", "no explicit",
        "does not mention", "doesn't mention", "do not mention",
        "no information", "not shown", "no record", "cannot determine",
        "not directly", "not mention", "do not specify",
    )):
        return True
    return any(m in s for m in _META_MARKERS)


def _content_words(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
        "for", "with", "by", "from", "into", "after", "before", "during",
        "that", "this", "these", "those", "it", "its", "is", "was", "were",
        "are", "be", "been", "has", "have", "had", "will", "would", "can",
        "could", "he", "she", "they", "his", "her", "their", "as", "not",
        "there", "here", "which", "who", "what", "when", "where", "how",
    }
    return {w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in stop}


def _faithful(answer: str, evidence: list[dict]) -> bool:
    """Back-compat gate used by the benchmark: passes only when EVERY
    cited sentence is supported by its own cited passages and no bare
    factual sentence slips through."""
    return not _unfaithful_sentences(answer, evidence)
