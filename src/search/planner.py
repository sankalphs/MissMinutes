"""Query understanding — natural language -> structured search plan (spec:15).

The LLM produces the PLAN, never the answer. Simple entity-only queries
skip the LLM entirely (spec:31).
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from src.llm.client import GMIClient

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

_ALLOWED_OPERATIONS = {
    "find_entity", "find_events", "next_events", "prev_events",
    "between_events", "find_connection", "caused_by", "free_search",
}


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
        "mcu", "whatif", "sony:rami", "sony:webb", "sony:ssu", "sony:spiderverse",
        "fox:xmen", "fox:ff", "defenders"
    ] | None = None
    temporal_constraint: str | None = None


SIMPLE_NAME = re.compile(r"^[A-Z][A-Za-z0-9 .'\-]{1,40}$")


def parse_query(llm: GMIClient, query: str) -> QueryPlan:
    # spec:31 — simple single-name queries skip the LLM
    if SIMPLE_NAME.match(query.strip()) and len(query.strip().split()) <= 4:
        return QueryPlan(entities=[query.strip()], intent="entity_lookup", operation="find_entity")
    try:
        raw = llm.chat_json(
            [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        return QueryPlan(**raw)
    except (ValidationError, Exception):
        return QueryPlan(entities=[], intent="semantic", operation="free_search")
