"""SQLite provenance store — documents, chunks, FTS5 lexical index.

Single-file DB (data/missminutes.db). Chunk rows carry exact source
coordinates (document_id, chunk_id, cue range, timecodes) so every KG fact
and citation can point back to subtitle evidence (spec:5,6,20).

One process-long connection shared across worker threads (gradio rotates
its handler threads): check_same_thread=False + a lock — sqlite3 objects
default to creator-thread-only and every cross-thread query raised
ProgrammingError, silently killing the lexical leg.
"""
import sqlite3
import threading
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
        self._lock = threading.RLock()
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.execute("PRAGMA busy_timeout = 5000")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self) -> None:
        with self._lock:
            self.con.close()

    # every access goes through the lock — one connection, many threads.
    # Rows are materialized before the lock releases: returning a live
    # cursor would let fetches race another thread's writes.
    def _execute(self, sql: str, params: tuple | list = ()) -> list[tuple]:  # noqa: ANN401
        with self._lock:
            return self.con.execute(sql, params).fetchall()

    def _executemany(self, sql: str, rows: list) -> None:
        with self._lock:
            self.con.executemany(sql, rows)

    def _commit(self) -> None:
        with self._lock:
            self.con.commit()

    # ---------- documents ----------

    def upsert_document(self, doc: dict) -> None:
        with self._lock:
            self.con.execute(
                """INSERT INTO documents (document_id, slug, title, year, type, timeline_id,
                    canonical, animated, season, episode, imdb_id, source, release,
                    cue_count, chunk_count, ingested_at)
                   VALUES (:document_id, :slug, :title, :year, :type, :timeline_id,
                    :canonical, :animated, :season, :episode, :imdb_id, :source, :release,
                    :cue_count, :chunk_count, :ingested_at)
                   ON CONFLICT(document_id) DO UPDATE SET
                    title=excluded.title, year=excluded.year, type=excluded.type,
                    timeline_id=excluded.timeline_id, canonical=excluded.canonical,
                    animated=excluded.animated, season=excluded.season,
                    episode=excluded.episode, imdb_id=excluded.imdb_id,
                    release=excluded.release, cue_count=excluded.cue_count,
                    chunk_count=excluded.chunk_count, ingested_at=excluded.ingested_at,
                    source=excluded.source""",
                doc,
            )
            self.con.commit()

    def has_document(self, document_id: str) -> bool:
        rows = self._execute(
            "SELECT 1 FROM documents WHERE document_id = ? LIMIT 1", (document_id,)
        )
        return rows != []

    # ---------- chunks ----------

    def replace_chunks(self, document_id: str, chunks: list[dict]) -> None:
        with self._lock:
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
        return self._execute("SELECT COUNT(*) FROM documents")[0][0]

    def chunk_count(self) -> int:
        return self._execute("SELECT COUNT(*) FROM chunks")[0][0]

    @staticmethod
    def _fts_match(query: str) -> str:
        """Re-quote the query term-by-term: user syntax (*, -, parens, NEAR,
        bare AND/OR) must never crash the MATCH. Terms become quoted
        phrases joined by implicit AND; embedded quotes are dropped."""
        return " ".join(
            '"' + t.replace('"', "") + '"' for t in query.split() if t.strip()
        )

    def fts_search(self, query: str, limit: int = 20, timeline: str | None = None,
                   rank: bool = False, raw: bool = False) -> list[dict]:
        """FTS5 lexical search; timeline filter enforces scope truthfully.
        rank=True orders by bm25 (relevance instead of rowid order) and
        attaches a `bm25` score — higher = better (negated FTS5 bm25).
        raw=True trusts a caller-built MATCH expression (hybrid's quoted
        terms) — _fts_match would re-quote the quotes and destroy the ORs."""
        match = query if raw else self._fts_match(query)
        if not match:
            return []
        cols = "f.chunk_id, f.document_id, f.text, d.title, d.timeline_id"
        if rank:
            cols += ", -bm25(chunks_fts) AS bm25"
        sql = f"""SELECT {cols}
                 FROM chunks_fts f JOIN documents d ON d.document_id = f.document_id
                 WHERE chunks_fts MATCH ?"""
        params: list = [match]
        if timeline:
            sql += " AND d.timeline_id = ?"
            params.append(timeline)
        if rank:
            sql += " ORDER BY bm25 DESC LIMIT ?"  # bm25 alias is negated: higher = better
        else:
            sql += " LIMIT ?"
        params.append(limit)
        rows = self._execute(sql, params)
        keys = ["chunk_id", "document_id", "text", "title", "timeline_id"] + (["bm25"] if rank else [])
        return [dict(zip(keys, r)) for r in rows]

    def get_chunk(self, chunk_id: str) -> dict | None:
        rows = self._execute(
            "SELECT chunk_id, document_id, text FROM chunks WHERE chunk_id = ?", (chunk_id,)
        )
        if not rows:
            return None
        r = rows[0]
        return {"chunk_id": r[0], "document_id": r[1], "text": r[2]}

    def get_chunk_times(self, chunk_id: str) -> dict | None:
        """Source coordinates in seconds — lets the retrieval eval match
        golden cue windows against retrieved chunks without re-parsing."""
        rows = self._execute(
            "SELECT document_id, start_ms, end_ms FROM chunks WHERE chunk_id = ?",
            (chunk_id,),
        )
        if not rows:
            return None
        return {
            "document_id": rows[0][0],
            "start_s": rows[0][1] / 1000.0,
            "end_s": rows[0][2] / 1000.0,
        }

    def get_document(self, document_id: str) -> dict | None:
        rows = self._execute(
            "SELECT document_id, slug, title, year, type, timeline_id, canonical, "
            "season, episode, source FROM documents WHERE document_id = ?",
            (document_id,),
        )
        if not rows:
            return None
        keys = ["document_id", "slug", "title", "year", "type", "timeline_id",
                "canonical", "season", "episode", "source"]
        return dict(zip(keys, rows[0]))

    def all_documents(self) -> list[dict]:
        rows = self._execute(
            "SELECT document_id, slug, title, year, type, timeline_id, canonical, "
            "season, episode, imdb_id, chunk_count FROM documents ORDER BY timeline_id, year"
        )
        keys = ["document_id", "slug", "title", "year", "type", "timeline_id",
                "canonical", "season", "episode", "imdb_id", "chunk_count"]
        return [dict(zip(keys, r)) for r in rows]
