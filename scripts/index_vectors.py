"""Index all SQLite chunks into Qdrant with embeddings.

Run: python scripts/index_vectors.py [--limit N] [--doc-prefix doc:loki]
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.store import Store  # noqa: E402
from src.vector.qdrant import VectorStore, chunk_point_id, embed_texts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("index")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--doc-prefix", type=str, default=None)
    args = ap.parse_args()

    store = Store()
    vs = VectorStore()
    vs.ensure_collection()

    con = store.con
    sql = (
        "SELECT c.chunk_id, c.document_id, c.text, d.title, d.timeline_id "
        "FROM chunks c JOIN documents d ON d.document_id = c.document_id"
    )
    params: list = []
    if args.doc_prefix:
        sql += " WHERE c.document_id LIKE ?"
        params.append(f"{args.doc_prefix}%")
    cur = con.execute(sql, params)
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]

    log.info("embedding %d chunks...", len(rows))
    batch_size = 64
    done = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        vectors = embed_texts([r[2] for r in batch])
        points = [
            {
                "id": chunk_point_id(r[0]),
                "vector": v,
                "payload": {
                    "chunk_id": r[0],
                    "document_id": r[1],
                    "title": r[3],
                    "timeline_id": r[4],
                    "text": r[2][:4096],
                },
            }
            for r, v in zip(batch, vectors)
        ]
        vs.upsert_chunks(points)
        done += len(batch)
        log.info("  %d / %d", done, len(rows))
    log.info("qdrant now holds %d points", vs.count())


if __name__ == "__main__":
    main()
