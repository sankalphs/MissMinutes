"""Query understanding — natural language -> structured search plan (spec:15).

The LLM produces the PLAN, never the answer. Simple entity-only queries
skip the LLM entirely (spec:31).
"""
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.llm.client import GMIClient

logger = logging.getLogger(__name__)

PLAN_SYSTEM = """You convert user questions about Marvel screen canon into a JSON search plan.
Output ONLY JSON:
{"entities": [str], "intent": "entity_lookup|event_lookup|timeline_query|connection_query|semantic",
 "operation": "find_entity|find_events|next_events|prev_events|between_events|find_connection|caused_by|free_search",
 "reference_event": str|null,
 "timeline": str|null,
 "temporal_constraint": str|null}
Timeline must be one of: "mcu", "whatif", "sony:rami", "sony:webb", "sony:ssu", "sony:spiderverse", "fox:xmen", "fox:ff", "defenders" or null.
If the question names an event and asks what happened after/before it, put the event in reference_event
and use next_events/prev_events."""

_ALLOWED_INTENTS = {
    "entity_lookup", "event_lookup", "timeline_query", "connection_query", "semantic"
}

_ALLOWED_OPERATIONS = {
    "find_entity", "find_events", "next_events", "prev_events",
    "between_events", "find_connection", "caused_by", "free_search",
}

TIMELINE_KEYS = {"mcu", "whatif", "sony:rami", "sony:webb", "sony:ssu",
                 "sony:spiderverse", "fox:xmen", "fox:ff", "defenders"}


class QueryPlan(BaseModel):
    entities: list[str] = Field(default_factory=list, max_length=6)
    intent: Literal[
        "entity_lookup", "event_lookup", "timeline_query", "connection_query", "semantic"
    ] = "semantic"
    operation: Literal[
        "find_entity", "find_events", "next_events", "prev_events",
        "between_events", "find_connection", "caused_by", "free_search"
    ] = "free_search"
    reference_event: str | None = None
    timeline: Literal[
        "mcu", "whatif", "sony:rami", "sony:webb", "sony:ssu",
        "sony:spiderverse", "fox:xmen", "fox:ff", "defenders"
    ] | None = None
    temporal_constraint: str | None = None


# Bare names only, 1-4 capitalized words ("Loki", "The Avengers"). A
# question shape ("Who is Loki", "What is the TVA") must never match —
# it previously captured the whole sentence as an entity.
SIMPLE_NAME = re.compile(r"^(?:the\s+)?[A-Z][a-zA-Z'.-]*(?:\s+[A-Z][a-zA-Z'.-]*){0,3}$")


def _is_simple_name(q: str) -> bool:
    if not SIMPLE_NAME.match(q):
        return False
    if q.strip().endswith(("?", ".", "!", ",")):
        return False
    # every word must start a capital run (no lowercase sentence starts)
    return all(w[0].isupper() for w in q.split() if w)


def _coerce_plan(raw: Any) -> dict:
    """Salvage a mostly-valid LLM plan: truncate entity overflow and drop
    fields outside the allowed literals (model defaults then apply). One
    over-long field must not throw away an otherwise valid plan."""
    coerced = dict(raw) if isinstance(raw, dict) else {}
    entities = coerced.get("entities") or []
    coerced["entities"] = [str(e).strip() for e in entities if str(e).strip()][:6]
    for field, allowed in (
        ("intent", _ALLOWED_INTENTS),
        ("operation", _ALLOWED_OPERATIONS),
        ("timeline", TIMELINE_KEYS),
    ):
        if coerced.get(field) is not None and coerced[field] not in allowed:
            coerced.pop(field)
    for field in ("reference_event", "temporal_constraint"):
        if coerced.get(field) is not None:
            coerced[field] = str(coerced[field])[:160] or None
    return coerced


def parse_query(llm: GMIClient, query: str) -> QueryPlan:
    # spec:31 — simple single-name queries skip the LLM
    q = query.strip()
    if _is_simple_name(q):
        return QueryPlan(entities=[q], intent="entity_lookup", operation="find_entity")
    try:
        raw = llm.chat_json(
            [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        try:
            return QueryPlan(**raw)
        except ValidationError:
            return QueryPlan(**_coerce_plan(raw))
    except Exception as e:
        # degraded plan: semantic-only, no entities. Logged — silent
        # degradation is a lie the status line would repeat.
        logger.warning("query planning degraded to free_search: %s", e)
        return QueryPlan(entities=[], intent="semantic", operation="free_search")
