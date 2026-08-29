import json
from pathlib import Path

import pytest

from src.config import settings

INVENTORY = settings.CANON_DIR / "inventory.json"


@pytest.fixture(scope="module")
def inv() -> list[dict]:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_exists_and_unique_slugs(inv: list[dict]) -> None:
    slugs = [e["slug"] for e in inv]
    assert len(slugs) == len(set(slugs)), "duplicate slugs"


def test_imdb_ids_valid(inv: list[dict]) -> None:
    for e in inv:
        assert e["imdb_id"].startswith("tt"), f"{e['slug']}: bad id {e['imdb_id']}"
        assert e.get("imdb_id_verified"), f"{e['slug']}: unverified"


def test_imdb_ids_unique(inv: list[dict]) -> None:
    ids = [e["imdb_id"] for e in inv]
    assert len(ids) == len(set(ids)), "duplicate imdb ids across titles"


def test_timeline_ids_allowed(inv: list[dict]) -> None:
    allowed = {"mcu", "whatif", "sony:rami", "sony:webb", "sony:ssu", "fox:xmen", "defenders"}
    for e in inv:
        assert e["timeline_id"] in allowed, f"{e['slug']}: {e['timeline_id']}"


def test_series_have_episode_counts(inv: list[dict]) -> None:
    for e in inv:
        if e["type"] == "series":
            assert e.get("episode_counts"), f"{e['slug']}: no episode_counts"
            assert sum(int(v) for v in e["episode_counts"].values()) > 0
