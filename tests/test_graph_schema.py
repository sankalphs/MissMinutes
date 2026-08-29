import pytest

from src.graph.schema import NODE_LABELS, REL_TYPES, TIMELINE_SEED, Graph


def test_allowlists_static() -> None:
    assert "Character" in NODE_LABELS and "Timeline" in NODE_LABELS
    assert "BEFORE" in REL_TYPES and "CAUSES" in REL_TYPES and "BRANCHES_FROM" in REL_TYPES
    assert len(TIMELINE_SEED) == 7
    ids = [t["id"] for t in TIMELINE_SEED]
    assert "timeline:mcu" in ids and "timeline:fox:xmen" in ids
    # parent references must exist
    for t in TIMELINE_SEED:
        assert t["parent"] is None or t["parent"] in ids


def test_graph_rejects_bad_label_and_rel() -> None:
    g = Graph.__new__(Graph)  # no driver; only testing guards
    with pytest.raises(AssertionError):
        g.merge_entity({"id": "x", "name": "x", "type": "Villain"}, {})
    with pytest.raises(AssertionError):
        g.merge_rel("a", "TELEPORTS_TO", "b", {})


def test_chunk_point_id_stable() -> None:
    from src.vector.qdrant import chunk_point_id

    assert chunk_point_id("doc:x") == chunk_point_id("doc:x")
    assert chunk_point_id("doc:x") != chunk_point_id("doc:y")
    assert 0 <= chunk_point_id("doc:x") < 2**63
