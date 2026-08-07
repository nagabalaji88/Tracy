"""SQLite connection management. No ORM, no migrations — a POC store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.schema_def import SCHEMA_SQL

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "control_plane.db"
FIXTURES_DIR = BACKEND_DIR / "fixtures"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS n FROM traces").fetchone()
    return row["n"] == 0
