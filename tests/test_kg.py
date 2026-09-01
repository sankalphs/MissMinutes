import json
import sqlite3
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
    import sqlite3

    con = sqlite3.connect(tmp_path / "kg.db")
    assert con.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 2
    con.close()


def test_resolver_type_disambiguation(tmp_path: Path) -> None:
    r = EntityResolver(db_path=tmp_path / "kg.db")
    r.register("SHIELD", "Organization", ["S.H.I.E.L.D."])
    r.register("Captain America's Shield", "Object", ["Shield"])
    # alias 'S.H.I.E.L.D.' -> org; alias 'Shield' -> object; type decides
    assert r.resolve("S.H.I.E.L.D.", "Organization") == "organization:shield"
    assert r.resolve("Shield", "Object") == "object:captain_americas_shield"
    # 'shield' with Organization type must NOT become the shield object
    cid = r.register("SHIELD", "Organization", ["S.H.I.E.L.D."])
    assert cid == "organization:shield"
    assert r.resolve("Stark", "Character") != r.resolve("Stark Industries", "Organization")


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


# ---------- loader: every registered endpoint must get a node write ----------

class _FakeResult:
    def __init__(self, params: dict) -> None:
        self._params = params

    def single(self) -> dict:
        rows = self._params.get("rows", [])
        return {"written": len(rows), "missing_timeline": 0, "missing_document": 0}


class FakeGraph:
    """Records every Cypher statement so tests can assert graph writes."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict]] = []

    def session(self):
        return self

    def __enter__(self) -> "FakeGraph":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def run(self, query: str, **params) -> _FakeResult:
        self.writes.append((query, params))
        return _FakeResult(params)

    def nodes_written(self, label: str) -> list[dict]:
        out = []
        for query, params in self.writes:
            if f"MERGE (n:{label}" in query:
                out.extend(params["rows"])
        return out


def _setup_store(tmp_path: Path, doc_overrides: dict | None = None):
    from src.ingestion.store import Store
    from src.kg.extract import ensure_cache

    store = Store(path=tmp_path / "mm.db")
    doc = {
        "document_id": "doc:fake_2021_s01e01", "slug": "fake-2021", "title": "Fake Show",
        "year": 2021, "type": "series", "timeline_id": "mcu", "canonical": 1,
        "animated": 0, "season": 1, "episode": 1, "imdb_id": "tt0000001",
        "source": "test", "release": "2021", "cue_count": 1, "chunk_count": 1,
        "ingested_at": "2026-01-01",
    }
    doc.update(doc_overrides or {})
    store.upsert_document(doc)
    ensure_cache(store.path)
    return store


def _cache_extraction(store, chunk_id: str, raw: dict) -> None:
    con = sqlite3.connect(store.path)
    con.execute(
        "INSERT INTO extractions (chunk_id, model, status, raw, error, extracted_at) VALUES (?, ?, 'ok', ?, NULL, '2026-01-01')",
        (chunk_id, "test-model", json.dumps(raw)),
    )
    con.commit()
    con.close()


def test_event_participants_get_nodes_and_edges(tmp_path: Path) -> None:
    store = _setup_store(tmp_path)
    _cache_extraction(store, "doc:fake_2021_s01e01#c0", {
        "entities": [],
        "events": [{
            "name": "Jane Doe finds the orb",
            "participants": ["Jane Doe"],
            "objects": ["Magic Orb"],
            "location": "Smallville",
            "date": None, "date_precision": "unknown",
            "evidence_quote": "Jane picked up the orb in Smallville.",
        }],
        "relations": [],
        "temporals": [],
    })
    graph = FakeGraph()
    resolver = EntityResolver(db_path=tmp_path / "kg.db", seed=False)
    from src.kg.load import load_all
    totals = load_all(graph, resolver, store, model="test-model")

    ev_id = canonical_id("event", "Jane Doe finds the orb")
    char_rows = graph.nodes_written("Character")
    assert {"id": canonical_id("character", "Jane Doe")} in [{"id": r["id"]} for r in char_rows]
    assert {"id": canonical_id("object", "Magic Orb")} in [{"id": r["id"]} for r in graph.nodes_written("Object")]
    assert {"id": canonical_id("location", "Smallville")} in [{"id": r["id"]} for r in graph.nodes_written("Location")]

    def rel_pairs(rel: str) -> list[dict]:
        return [{"src": r["src"], "dst": r["dst"]}
                for q, p in graph.writes if rel in q for r in p["rows"]]

    assert {"src": canonical_id("character", "Jane Doe"), "dst": ev_id} in rel_pairs("PARTICIPATES_IN")
    assert {"src": ev_id, "dst": canonical_id("object", "Magic Orb")} in rel_pairs("INVOLVES")
    assert {"src": ev_id, "dst": canonical_id("location", "Smallville")} in rel_pairs("OCCURS_AT")
    assert totals["nodes"] >= 4  # event + participant + object + location


def test_relation_and_temporal_endpoints_get_nodes(tmp_path: Path) -> None:
    store = _setup_store(tmp_path)
    _cache_extraction(store, "doc:fake_2021_s01e01#c0", {
        "entities": [],
        "events": [],
        "relations": [{"source": "Ann", "relation": "KNOWS", "target": "Bob",
                       "evidence_quote": "Ann has known Bob for years."}],
        "temporals": [{"event_a": "The big blast", "event_b": "The quiet after",
                       "relation": "BEFORE", "evidence_quote": "First the blast, then silence."}],
    })
    graph = FakeGraph()
    resolver = EntityResolver(db_path=tmp_path / "kg.db", seed=False)
    from src.kg.load import load_all
    load_all(graph, resolver, store, model="test-model")

    char_ids = {r["id"] for r in graph.nodes_written("Character")}
    assert canonical_id("character", "Ann") in char_ids
    assert canonical_id("character", "Bob") in char_ids
    event_ids = {r["id"] for r in graph.nodes_written("Event")}
    assert canonical_id("event", "The big blast") in event_ids
    assert canonical_id("event", "The quiet after") in event_ids

    rel_pairs = [{"src": r["src"], "dst": r["dst"]}
                 for q, p in graph.writes if "KNOWS" in q for r in p["rows"]]
    assert {"src": canonical_id("character", "Ann"), "dst": canonical_id("character", "Bob")} in rel_pairs


def test_series_document_without_season_gets_series_node(tmp_path: Path) -> None:
    store = _setup_store(tmp_path, {"season": None, "episode": None})
    graph = FakeGraph()
    resolver = EntityResolver(db_path=tmp_path / "kg.db", seed=False)
    from src.kg.load import load_all
    load_all(graph, resolver, store, model="test-model")

    series_merges = [p for q, p in graph.writes if "MERGE (s:Series {id: $id})" in q]
    assert series_merges and series_merges[0]["id"] == "doc:fake_2021_s01e01"


def test_resolver_entity_accessor(tmp_path: Path) -> None:
    r = EntityResolver(db_path=tmp_path / "kg.db", seed=False)
    cid = r.register("Jane Doe", "Character", ["JD"])
    assert r.entity(cid)["name"] == "Jane Doe"
    assert r.entity(cid)["aliases"] == ["JD"]
    assert r.entity("character:missing") is None
