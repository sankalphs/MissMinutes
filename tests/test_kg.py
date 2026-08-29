import json
from pathlib import Path

import pytest

from src.kg.schemas import ChunkExtraction, ExtractedEntity, ExtractedEvent, ExtractedRelation, ExtractedTemporal
from src.kg.resolve import EntityResolver, canonical_id


def test_entity_validation_rejects_noise() -> None:
    with pytest.raises(Exception):
        ExtractedEntity(name="", type="Character")
    with pytest.raises(Exception):
        ExtractedEntity(name="42", type="Character")
    e = ExtractedEntity(name=" Loki ", type="Character", aliases=["God of Mischief"])
    assert e.name == "Loki" and e.aliases == ["God of Mischief"]


def test_chunk_extraction_rejects_self_relations() -> None:
    good = ExtractedRelation(source="Loki", relation="USES", target="Tesseract", evidence_quote="Loki grabs the Tesseract")
    bad = ExtractedRelation(source="Loki", relation="USES", target="Loki", evidence_quote="Loki uses Loki")
    ex = ChunkExtraction(entities=[], events=[], relations=[good, bad], temporals=[])
    assert len(ex.relations) == 1 and ex.relations[0].target == "Tesseract"


def test_canonical_ids_deterministic() -> None:
    assert canonical_id("character", "Loki") == "character:loki"
    assert canonical_id("character", "Loki Laufeyson") == "character:loki_laufeyson"
    assert canonical_id("object", "The Tesseract") == "object:tesseract"


def test_resolver_alias_and_case_match(tmp_path: Path) -> None:
    r = EntityResolver(db_path=tmp_path / "kg.db")
    cid1 = r.register("Loki", "Character", ["God of Mischief", "Loki Laufeyson"])
    assert r.resolve("loki", "Character") == cid1
    assert r.resolve("God of Mischief", "Character") == cid1
    assert r.resolve("LOKI LAUFEYSON", "Character") == cid1
    assert r.resolve("Mobius", "Character") == "character:mobius"
    ents = r.known_entities()
    assert any(e["name"] == "Loki" for e in ents)
    r.record_conflict("event:battle_of_new_york", "date=2013", "The Avengers", 0.5)
    r.record_conflict("event:battle_of_new_york", "date=2012", "The Avengers", 0.95)
    con = r._conn()
    assert con.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 2
    con.close()


def test_valid_full_extraction_parses() -> None:
    raw = json.dumps(
        {
            "entities": [
                {"name": "Loki", "type": "Character", "aliases": []},
                {"name": "Tesseract", "type": "Object", "aliases": []},
            ],
            "events": [
                {
                    "name": "Loki steals the Tesseract",
                    "participants": ["Loki"],
                    "objects": ["Tesseract"],
                    "location": "Asgard",
                    "date": "2012",
                    "date_precision": "year",
                    "evidence_quote": "My brother took it from the vault on Asgard.",
                }
            ],
            "relations": [
                {"source": "Loki", "relation": "USES", "target": "Tesseract",
                 "evidence_quote": "Loki has it."}
            ],
            "temporals": [
                {"event_a": "Loki steals the Tesseract",
                 "event_b": "SHIELD tracks the Scepter to Stuttgart",
                 "relation": "BEFORE",
                 "evidence_quote": "Two days ago..."}
            ],
        }
    )
    ex = ChunkExtraction(**json.loads(raw))
    assert ex.events[0].date_precision == "year"
    assert ex.temporals[0].relation == "BEFORE"
