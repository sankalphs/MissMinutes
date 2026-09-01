"""Vector-store unit tests that need no Qdrant connection."""
from src.vector.qdrant import chunk_point_id


def test_chunk_point_id_is_deterministic() -> None:
    assert chunk_point_id("doc:a#s0000c00001") == chunk_point_id("doc:a#s0000c00001")


def test_chunk_point_id_distinct_for_distinct_chunks() -> None:
    ids = {chunk_point_id(f"doc:a#s{i:05d}") for i in range(1000)}
    assert len(ids) == 1000, "hash collision across 1000 sequential ids"


def test_chunk_point_id_stays_in_unsigned_range() -> None:
    """Qdrant point ids are unsigned 64-bit — a negative or overflowing id
    is rejected at upsert time, so the hash must stay 60-bit positive."""
    for i in range(200):
        pid = chunk_point_id(f"doc:b#s{i:05d}")
        assert 0 <= pid < 2**63
