"""Qdrant vector store — cloud if QDRANT_URL set, local fallback otherwise.

The qdrant-client API is identical for local and cloud, so swapping is just
an env var. Collection: missminutes_chunks (384d bge-small-en-v1.5 embeddings).
Chunk payloads carry full provenance (document_id, timeline_id, title,
cue range) so vector hits map straight to citable evidence (spec:14,20).
"""
import logging
import threading
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


def make_client():
    from qdrant_client import QdrantClient

    if settings.QDRANT_URL:
        logger.info("qdrant: cloud %s", settings.QDRANT_URL)
        return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=30)
    logger.warning("qdrant: QDRANT_URL unset — using LOCAL persistence data/processed/qdrant")
    return QdrantClient(path=str(settings.PROCESSED_DIR / "qdrant"))


class VectorStore:
    def __init__(self) -> None:
        self.client = make_client()
        self.collection = settings.QDRANT_COLLECTION

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            from qdrant_client.models import Distance, VectorParams

            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info("created collection %s (dim=%d)", self.collection, settings.EMBEDDING_DIM)

    def upsert_chunks(self, points: list[dict[str, Any]]) -> None:
        """points: [{id, vector, payload}] — id = stable hash of chunk_id."""
        from qdrant_client.models import PointStruct

        self.ensure_collection()
        batch = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ]
        # upsert in batches of 256
        for i in range(0, len(batch), 256):
            self.client.upsert(collection_name=self.collection, points=batch[i : i + 256])

    def search(self, vector: list[float], limit: int = 10, timeline: str | None = None) -> list[dict]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        flt = None
        if timeline:
            flt = Filter(must=[FieldCondition(key="timeline_id", match=MatchValue(value=timeline))])
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=flt,
            with_payload=True,
        ).points
        return [
            {
                "chunk_id": h.payload.get("chunk_id"),
                "document_id": h.payload.get("document_id"),
                "title": h.payload.get("title"),
                "timeline_id": h.payload.get("timeline_id"),
                "text": h.payload.get("text"),
                "score": h.score,
            }
            for h in hits
        ]

    def count(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return self.client.count(self.collection, exact=True).count

    def health(self) -> dict:
        mode = "cloud" if settings.QDRANT_URL else "local"
        return {"ok": True, "mode": mode, "collection": self.collection, "points": self.count()}


_MODEL = None
_MODEL_LOCK = threading.Lock()


def _model():
    """Load the embedding model once per process (race-safe)."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                from sentence_transformers import SentenceTransformer

                _MODEL = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _MODEL


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed with bge-small-en-v1.5 (384d). Loads model once per process.
    The 2048-char slice is cosmetic — the tokenizer's 512-token window
    truncates long text regardless; chunks max out around 1400 chars."""
    model = _model()
    vecs = model.encode(
        [f"passage: {t[:2048]}" for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    model = _model()
    v = model.encode(f"query: {text}", normalize_embeddings=True, show_progress_bar=False)
    return v.tolist()


def chunk_point_id(chunk_id: str) -> int:
    """Stable point id from chunk_id: first 15 hex digits = 60 bits, always
    within Qdrant's unsigned-int (and JSON-safe signed) range. A collision
    would silently overwrite the earlier chunk's point — the corpus is
    ~10^5 chunks, birthday risk is negligible at 2^60."""
    import hashlib

    return int(hashlib.sha256(chunk_id.encode()).hexdigest()[:15], 16)
