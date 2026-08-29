import sys
from pathlib import Path


def test_config_loads_all_secrets() -> None:
    from src.config import settings

    assert settings.GMI_BASE_URL.startswith("https://")
    assert settings.GMI_MODEL == "MiniMaxAI/MiniMax-M3"
    assert settings.GMI_API_KEY, "GMI key missing"
    assert settings.WYZIE_API_KEY.startswith("wyzie-"), "Wyzie key missing"
    assert settings.NEO4J_URI.startswith("neo4j+s://"), "Aura URI missing"
    assert settings.NEO4J_PASSWORD, "Aura password missing"
    assert settings.QDRANT_API_KEY, "Qdrant key missing"
    assert settings.EMBEDDING_DIM == 384


def test_gmi_client_shapes() -> None:
    from src.llm.client import GMIClient

    c = GMIClient()
    assert c.model == "MiniMaxAI/MiniMax-M3"
    assert c.base_url.endswith("/v1")
