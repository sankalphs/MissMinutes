"""SQLite provenance store — documents, chunks, FTS5 lexical index.

Single-file DB (data/missminutes.db). Chunk rows carry exact source
coordinates (document_id, chunk_id, cue range, timecodes) so every KG fact
and citation can point back to subtitle evidence (spec:5,6,20).
"""
import json
import sqlite3
from pathlib import Path

from src.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    type TEXT NOT NULL,
    timeline_id TEXT NOT NULL,
    canonical INTEGER NOT NULL,
    animated INTEGER NOT NULL DEFAULT 0,
    season INTEGER,
    episode INTEGER,
    imdb_id TEXT,
    source TEXT,
    release TEXT,
    cue_count INTEGER,
    chunk_count INTEGER,
    ingested_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    scene_i INTEGER,
    cue_start INTEGER,
    cue_end INTEGER,
    start_ms INTEGER,
    end_ms INTEGER,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chunk_id UNINDEXED, document_id UNINDEXED
);
"""


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.DATABASE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    # ---------- documents ----------

    def upsert_document(self, doc: dict) -> None:
        self.con.execute(
            """INSERT INTO documents (document_id, slug, title, year, type, timeline_id,
                canonical, animated, season, episode, imdb_id, source, release,
                cue_count, chunk_count, ingested_at)
               VALUES (:document_id, :slug, :title, :year, :type, :timeline_id,
                :canonical, :animated, :season, :episode, :imdb_id, :source, :release,
                :cue_count, :chunk_count, :ingested_at)
               ON CONFLICT(document_id) DO UPDATE SET
                cue_count=excluded.cue_count, chunk_count=excluded.chunk_count,
                ingested_at=excluded.ingested_at, source=excluded.source""",
            doc,
        )
        self.con.commit()

    def has_document(self, document_id: str) -> bool:
        cur = self.con.execute(
            "SELECT 1 FROM documents WHERE document_id = ? LIMIT 1", (document_id,)
        )
        return cur.fetchone() is not None

    # ---------- chunks ----------

    def replace_chunks(self, document_id: str, chunks: list[dict]) -> None:
        self.con.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        self.con.execute(
            "DELETE FROM chunks_fts WHERE document_id = ?", (document_id,)
        )
        self.con.executemany(
            """INSERT OR REPLACE INTO chunks
               (chunk_id, document_id, scene_i, cue_start, cue_end, start_ms, end_ms, text)
               VALUES (:chunk_id, :document_id, :scene_i, :cue_start, :cue_end,
                :start_ms, :end_ms, :text)""",
            chunks,
        )
        self.con.executemany(
            "INSERT INTO chunks_fts (text, chunk_id, document_id) VALUES (?, ?, ?)",
            [(c["text"], c["chunk_id"], c["document_id"]) for c in chunks],
        )
        self.con.commit()

    # ---------- query ----------

    def doc_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def chunk_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def fts_search(self, query: str, limit: int = 20) -> list[dict]:
        cur = self.con.execute(
            """SELECT f.chunk_id, f.document_id, f.text, d.title, d.timeline_id
               FROM chunks_fts f JOIN documents d ON d.document_id = f.document_id
               WHERE chunks_fts MATCH ? LIMIT ?""",
            (query, limit),
        )
        return [
            {"chunk_id": r[0], "document_id": r[1], "text": r[2], "title": r[3], "timeline_id": r[4]}
            for r in cur.fetchall()
        ]

    def get_chunk(self, chunk_id: str) -> dict | None:
        cur = self.con.execute(
            "SELECT chunk_id, document_id, text FROM chunks WHERE chunk_id = ?", (chunk_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"chunk_id": row[0], "document_id": row[1], "text": row[2]}

    def get_document(self, document_id: str) -> dict | None:
        cur = self.con.execute(
            "SELECT document_id, slug, title, year, type, timeline_id, canonical, "
            "season, episode, source FROM documents WHERE document_id = ?",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        keys = ["document_id", "slug", "title", "year", "type", "timeline_id",
                "canonical", "season", "episode", "source"]
        return dict(zip(keys, row))

    def all_documents(self) -> list[dict]:
        cur = self.con.execute(
            "SELECT document_id, slug, title, year, type, timeline_id, canonical, "
            "season, episode, imdb_id, chunk_count FROM documents ORDER BY timeline_id, year"
        )
        keys = ["document_id", "slug", "title", "year", "type", "timeline_id",
                "canonical", "season", "episode", "imdb_id", "chunk_count"]
        return [dict(zip(keys, r)) for r in cur.fetchall()]
