"""Central config — loads .env once, exposes typed settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Settings:
    # LLM
    GMI_BASE_URL: str = os.getenv("GMI_BASE_URL", "https://api.gmi-serving.com/v1")
    GMI_API_KEY: str = os.getenv("GMI_API_KEY", "")
    GMI_MODEL: str = os.getenv("GMI_MODEL", "MiniMaxAI/MiniMax-M3")

    # Subtitles
    WYZIE_API_KEY: str = os.getenv("WYZIE_API_KEY", "")
    WYZIE_BASE_URL: str = os.getenv("WYZIE_BASE_URL", "https://sub.wyzie.io")
    WYZIE_DAILY_LIMIT: int = int(os.getenv("WYZIE_DAILY_LIMIT", "1000"))

    # Neo4j Aura
    NEO4J_URI: str = os.getenv("NEO4J_URI", "")
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "")

    # Qdrant Cloud
    QDRANT_URL: str = os.getenv("QDRANT_URL", "")
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")

    # Embeddings
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))

    # App
    DATABASE_PATH: Path = ROOT / os.getenv("DATABASE_PATH", "data/missminutes.db")
    DATA_DIR: Path = ROOT / "data"
    RAW_DIR: Path = ROOT / "data" / "raw"
    CANON_DIR: Path = ROOT / "data" / "canon"
    PROCESSED_DIR: Path = ROOT / "data" / "processed"
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")

    # Qdrant collection
    QDRANT_COLLECTION: str = "missminutes_chunks"
    GRAPH_PROJECT_ID: str = "missminutes"

    def ensure_dirs(self) -> None:
        for p in (self.DATA_DIR, self.RAW_DIR, self.CANON_DIR, self.PROCESSED_DIR):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
