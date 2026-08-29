"""Grounded answer generation + faithfulness gate (spec:19,21,33,37).

The synthesis LLM sees ONLY: the question, the query plan, graph results,
and retrieved evidence chunks. Every claim must cite [chunk_id] from the
evidence set. After generation, claims are re-checked against evidence
and unsupported claims trigger regeneration (once) or an uncertainty note.
"""
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.llm.client import GMIClient

logger = logging.getLogger(__name__)

ANSWER_SYSTEM = """You answer questions about Marvel screen canon using ONLY the supplied evidence.
Rules:
1. Use ONLY facts present in the EVIDENCE and GRAPH sections. Never use outside knowledge.
2. Every factual sentence must end with a citation marker like [1], [2] pointing into the evidence list.
3. If evidence is insufficient or conflicting, say so explicitly instead of guessing.
4. Preserve timeline distinctions (MCU/Sacred vs branches vs Sony/Fox timelines) when the evidence mentions them.
5. Output format:
   ANSWER: <2-6 sentences with [n] citations>
   UNCERTAINTY: <one sentence if anything is unclear/unsupported, else 'none'>
   SOURCES: <comma-separated list of source titles used>"""


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
        for i, e in enumerate(ev[:12])
    ]
    return "\n".join(lines), ev[:12]


def generate_answer(llm: GMIClient, question: str, ranked: dict[str, Any]) -> dict:
    evidence_text, evidence = build_evidence_context(ranked["results"])
    if not evidence:
        return {
            "answer": "I could not find evidence for this question in the ingested sources.",
            "uncertainty": "no evidence retrieved",
            "sources": [],
            "citations": [],
        }
    user = (
        f"QUESTION: {question}\n\n"
        f"EVIDENCE:\n{evidence_text}\n\n"
        f"Answer using only this evidence."
    )
    raw = llm.chat(
        [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    parsed = _parse_answer_block(raw, evidence)
    if not _faithful(parsed["answer"], evidence):
        logger.info("faithfulness gate tripped — regenerating")
        regen = llm.chat(
            [
                {"role": "system", "content": ANSWER_SYSTEM},
                {"role": "user", "content": user + "\n\nIMPORTANT: your previous attempt included "
                 "claims not present in the evidence. Strictly re-derive from evidence only."},
            ],
            temperature=0.0,
            max_tokens=800,
        )
        parsed2 = _parse_answer_block(regen, evidence)
        if _faithful(parsed2["answer"], evidence):
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


def _faithful(answer: str, evidence: list[dict]) -> bool:
    """Gate: every [n] citation must be in range; answer must contain at least
    one citation; and content words must overlap evidence."""
    cites = re.findall(r"\[(\d+)\]", answer)
    if not cites:
        return False
    if any(int(c) > len(evidence) for c in cites):
        return False
    ev_words = {w.lower() for e in evidence for w in re.findall(r"[a-zA-Z]{4,}", e["text"])}
    ans_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", answer)}
    if not ans_words:
        return False
    overlap = len(ans_words & ev_words) / len(ans_words)
    return overlap >= 0.3
