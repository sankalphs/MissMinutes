"""Shared SQLite connect helper for the ad-hoc connections outside Store.

Every caller gets the same busy timeout, so parallel extraction workers
and the ingest scripts never die on 'database is locked' while Store's
long-lived connection holds a write.
"""
import sqlite3
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA busy_timeout = 5000")
    return con
