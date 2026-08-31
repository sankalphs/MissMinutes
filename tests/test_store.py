import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.ingestion.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def _doc(document_id: str = "doc:loki_2021_s01e01", **over: object) -> dict:
    doc = {
        "document_id": document_id,
        "slug": "loki_2021",
        "title": "Loki",
        "year": 2021,
        "type": "series",
        "timeline_id": "mcu",
        "canonical": 1,
        "animated": 0,
        "season": 1,
        "episode": 1,
        "imdb_id": "tt9140554",
        "source": "opensubtitles",
        "release": "loki.s01e01",
        "cue_count": 10,
        "chunk_count": 2,
        "ingested_at": "2026-08-29T00:00:00+00:00",
    }
    doc.update(over)
    return doc


def _chunk(document_id: str, cid: str, text: str) -> dict:
    return {
        "chunk_id": f"{document_id}#{cid}",
        "document_id": document_id,
        "scene_i": 0,
        "cue_start": 1,
        "cue_end": 3,
        "start_ms": 1000,
        "end_ms": 9000,
        "text": text,
    }


def test_document_roundtrip(store: Store) -> None:
    store.upsert_document(_doc())
    assert store.has_document("doc:loki_2021_s01e01")
    got = store.get_document("doc:loki_2021_s01e01")
    assert got is not None and got["title"] == "Loki" and got["timeline_id"] == "mcu"


def test_chunks_and_fts(store: Store) -> None:
    store.upsert_document(_doc())
    store.replace_chunks(
        "doc:loki_2021_s01e01",
        [
            {
                "chunk_id": "doc:loki_2021_s01e01#s0000c00001",
                "document_id": "doc:loki_2021_s01e01",
                "scene_i": 0,
                "cue_start": 1,
                "cue_end": 3,
                "start_ms": 1000,
                "end_ms": 9000,
                "text": "Loki meets Mobius at the TVA. Time works differently here.",
            },
            {
                "chunk_id": "doc:loki_2021_s01e01#s0000c00004",
                "document_id": "doc:loki_2021_s01e01",
                "scene_i": 0,
                "cue_start": 4,
                "cue_end": 6,
                "start_ms": 10000,
                "end_ms": 20000,
                "text": "The Time Variance Authority protects the sacred timeline.",
            },
        ],
    )
    assert store.chunk_count() == 2
    hits = store.fts_search("TVA OR timeline")
    assert len(hits) >= 1
    assert any("sacred timeline" in h["text"] for h in hits)
    assert hits[0]["title"] == "Loki"
    got = store.get_chunk("doc:loki_2021_s01e01#s0000c00001")
    assert got is not None and "Mobius" in got["text"]


def test_fts_timeline_scope_is_enforced(store: Store) -> None:
    """A scoped search must never leak cross-timeline evidence."""
    store.upsert_document(_doc())
    store.upsert_document(_doc(
        "doc:x_men_2000", slug="x_men_2000", title="X-Men",
        timeline_id="fox:xmen", type="movie", year=2000, episode=None, season=None,
    ))
    store.replace_chunks("doc:loki_2021_s01e01",
                         [_chunk("doc:loki_2021_s01e01", "c1", "Wolverine hunts the timeline")])
    store.replace_chunks("doc:x_men_2000",
                         [_chunk("doc:x_men_2000", "c1", "Wolverine hunts the timeline")])

    all_hits = store.fts_search('"Wolverine"')
    assert {h["timeline_id"] for h in all_hits} == {"mcu", "fox:xmen"}

    scoped = store.fts_search('"Wolverine"', timeline="fox:xmen")
    assert scoped, "scoped FTS must return the fox:xmen row"
    assert all(h["timeline_id"] == "fox:xmen" for h in scoped), \
        "scoped lexical leg leaked cross-timeline evidence"


def test_replace_chunks_idempotent(store: Store) -> None:
    store.upsert_document(_doc())
    chunks = [
        {
            "chunk_id": "doc:loki_2021_s01e01#s0000c00001",
            "document_id": "doc:loki_2021_s01e01",
            "scene_i": 0,
            "cue_start": 1,
            "cue_end": 1,
            "start_ms": 0,
            "end_ms": 1000,
            "text": "hello",
        }
    ]
    store.replace_chunks("doc:loki_2021_s01e01", chunks)
    store.replace_chunks("doc:loki_2021_s01e01", chunks)
    assert store.chunk_count() == 1


def test_store_is_usable_across_threads(store: Store) -> None:
    """gradio rotates worker threads — a Store created on one thread must
    serve FTS on another (the old check_same_thread=True raised
    ProgrammingError on every foreign-thread query, silently killing the
    lexical leg)."""
    store.upsert_document(_doc())
    store.replace_chunks("doc:loki_2021_s01e01",
                         [_chunk("doc:loki_2021_s01e01", "c1", "Loki meets the Time Variance Authority")])

    results: dict[str, object] = {}

    def query_from_thread():
        try:
            results["hits"] = store.fts_search('"Loki"')
        except Exception as e:  # noqa: BLE001
            results["err"] = e

    t = threading.Thread(target=query_from_thread)
    t.start()
    t.join(timeout=10)
    assert results.get("err") is None, f"cross-thread query failed: {results.get('err')}"
    hits = results["hits"]
    assert hits and hits[0]["timeline_id"] == "mcu"


def test_wyzie_ledger(store: Store) -> None:
    """WyzieClient ledger shares the same DB; verify budget accounting."""
    from src.ingestion.wyzie import WyzieClient

    client = WyzieClient(db_path=store.path)
    day = client._utc_day()
    con = sqlite3.connect(store.path)
    con.execute(
        "INSERT INTO wyzie_ledger (ts, utc_day, kind, target, status) VALUES (?, ?, 'search', ?, 200)",
        ("t", day, "tt0848228"),
    )
    con.commit()
    con.close()
    assert client.spent_today() == 1
    assert client.already_searched("tt0848228")
    assert not client.already_searched("tt9140554/1/1")
