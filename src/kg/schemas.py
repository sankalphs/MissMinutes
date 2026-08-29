"""KG extraction schemas (Pydantic) — the gate between LLM output and graph.

Every LLM response must parse into these models before any graph write.
spec:7,8,9,10,11,40 — validation is rule-based first, LLM only re-queried
on ambiguity.
"""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EntityType(str, Enum):
    character = "Character"
    event = "Event"
    location = "Location"
    object = "Object"
    organization = "Organization"


class RelationType(str, Enum):
    participates_in = "PARTICIPATES_IN"
    uses = "USES"
    member_of = "MEMBER_OF"
    occurs_at = "OCCURS_AT"
    causes = "CAUSES"
    knows = "KNOWS"
    enemy_of = "ENEMY_OF"
    allied_with = "ALLIED_WITH"
    family_of = "FAMILY_OF"
    romantic_with = "ROMANTIC_WITH"


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    type: EntityType
    aliases: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("name")
    @classmethod
    def name_not_noise(cls, v: str) -> str:
        v = v.strip()
        if not v or v.isdigit():
            raise ValueError(f"invalid entity name: {v!r}")
        return v


class ExtractedEvent(BaseModel):
    name: str = Field(min_length=4, max_length=160)
    participants: list[str] = Field(default_factory=list, max_length=20)
    objects: list[str] = Field(default_factory=list, max_length=20)
    location: str | None = None
    date: str | None = None              # free-form; resolved separately
    date_precision: Literal["year", "month", "day", "unknown"] = "unknown"
    evidence_quote: str = Field(min_length=8, max_length=600)


class ExtractedRelation(BaseModel):
    source: str = Field(min_length=2)
    relation: RelationType
    target: str = Field(min_length=2)
    evidence_quote: str = Field(min_length=8, max_length=600)

    @field_validator("source", "target")
    @classmethod
    def strip_tokens(cls, v: str, info) -> str:
        return v.strip()


class ExtractedTemporal(BaseModel):
    event_a: str = Field(min_length=4)
    event_b: str = Field(min_length=4)
    relation: Literal["BEFORE", "AFTER", "DURING", "CAUSES"]
    evidence_quote: str = Field(min_length=8, max_length=600)


class ChunkExtraction(BaseModel):
    """One LLM call's full validated output for a chunk."""
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=30)
    events: list[ExtractedEvent] = Field(default_factory=list, max_length=10)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=30)
    temporals: list[ExtractedTemporal] = Field(default_factory=list, max_length=10)

    @field_validator("relations")
    @classmethod
    def no_self_relations(cls, rels: list[ExtractedRelation]) -> list[ExtractedRelation]:
        out = []
        for r in rels:
            if r.source.strip().lower() != r.target.strip().lower():
                out.append(r)
        return out
