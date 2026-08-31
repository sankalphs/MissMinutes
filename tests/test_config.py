import pytest

from src.config import settings

pytestmark = pytest.mark.skipif(
    not settings.GMI_API_KEY,
    reason="no .env secrets present — CI-safe skip",
)


def test_config_loads_all_secrets() -> None:
    from src.config import settings as s

    assert s.GMI_BASE_URL.startswith("https://")
    assert s.GMI_MODEL == "MiniMaxAI/MiniMax-M3"
    assert s.GMI_API_KEY, "GMI key missing"
    assert s.WYZIE_API_KEY.startswith("wyzie-"), "Wyzie key missing"
    assert s.NEO4J_URI.startswith("neo4j+s://"), "Aura URI missing"
    assert s.NEO4J_PASSWORD, "Aura password missing"
    assert s.QDRANT_API_KEY, "Qdrant key missing"
    assert s.EMBEDDING_DIM == 384


def test_gmi_client_shapes() -> None:
    from src.llm.client import GMIClient

    c = GMIClient()
    assert c.model == "MiniMaxAI/MiniMax-M3"
    assert c.base_url.endswith("/v1")
