"""Entity resolution — canonical IDs, alias table, embedding similarity.

spec:4,36 — deterministic slug IDs first, embedding cosine for near-matches,
LLM disambiguation only as last resort (not implemented here — resolver
flags candidates instead of auto-merging).
"""
import re
import sqlite3
from pathlib import Path

from src.config import settings

STOPWORDS = {"the", "a", "an", "of"}


def canonical_id(kind: str, name: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", name.lower()).split()
    words = [w for w in words if w not in STOPWORDS]
    return f"{kind}:" + "_".join(words) if words else f"{kind}:{name.lower().strip()}"


class EntityResolver:
    """Maps extracted names -> canonical ids, dedupes via alias table +
    embedding similarity. Backed by the same SQLite DB."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS entities (
                canonical_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases TEXT NOT NULL DEFAULT '[]',
                embedding BLOB
            )"""
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS conflicts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "subject TEXT, claim TEXT, source TEXT, confidence REAL, created_at TEXT)"
        )
        con.commit()
        con.close()
        self._embed_cache: dict[str, list[float]] = {}

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def resolve(self, name: str, entity_type: str) -> str:
        """Deterministic resolution: existing id by exact/alias/case-insensitive
        match, else new canonical id."""
        cid = canonical_id(entity_type.lower(), name)
        con = self._conn()
        cur = con.execute(
            "SELECT canonical_id, aliases FROM entities WHERE lower(canonical_name) = lower(?)",
            (name,),
        )
        row = cur.fetchone()
        if row:
            con.close()
            return row[0]
        cur = con.execute("SELECT canonical_id, aliases FROM entities")
        for existing_id, aliases_json in cur.fetchall():
            import json

            aliases = json.loads(aliases_json)
            if name.lower() in [a.lower() for a in aliases]:
                con.close()
                return existing_id
        con.close()
        return cid  # new entity

    def register(self, name: str, entity_type: str, aliases: list[str] | None = None) -> str:
        import json

        cid = self.resolve(name, entity_type)
        con = self._conn()
        existing = con.execute(
            "SELECT aliases FROM entities WHERE canonical_id = ?", (cid,)
        ).fetchone()
        merged = list(aliases or [])
        if existing:
            merged = sorted({*json.loads(existing[0]), *(aliases or [])})
        con.execute(
            """INSERT INTO entities (canonical_id, canonical_name, entity_type, aliases)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(canonical_id) DO UPDATE SET
                 aliases = excluded.aliases, canonical_name = excluded.canonical_name""",
            (cid, name, entity_type, json.dumps(merged)),
        )
        con.commit()
        con.close()
        return cid

    def known_entities(self) -> list[dict]:
        import json

        con = self._conn()
        rows = con.execute(
            "SELECT canonical_id, canonical_name, entity_type, aliases FROM entities"
        ).fetchall()
        con.close()
        return [
            {"id": r[0], "name": r[1], "type": r[2], "aliases": json.loads(r[3])}
            for r in rows
        ]

    def record_conflict(self, subject: str, claim: str, source: str, confidence: float) -> None:
        from datetime import datetime, timezone

        con = self._conn()
        con.execute(
            "INSERT INTO conflicts (subject, claim, source, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
            (subject, claim, source, confidence, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        con.close()
