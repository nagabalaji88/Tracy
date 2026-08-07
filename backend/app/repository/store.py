"""
Repository layer. SQL in, plain dicts out.

Nothing above this layer knows sqlite exists; nothing in this layer knows what a
quality floor is.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.db import FIXTURES_DIR, connect, init_schema, is_empty
from app.schema_def import OUTCOME_COLUMNS, TRACE_COLUMNS


class DataError(RuntimeError):
    """Raised when the store cannot answer a question with recorded data."""


# --- seeding -----------------------------------------------------------------
def _insert_many(conn: sqlite3.Connection, table: str, columns: tuple[str, ...],
                 rows: Iterable[dict]) -> int:
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    payload = [tuple(row.get(col) for col in columns) for row in rows]
    conn.executemany(sql, payload)
    return len(payload)


def seed_from_fixtures(conn: sqlite3.Connection, fixtures_dir: Path | None = None) -> dict[str, int]:
    """
    Load the recorded runs. Idempotent: it truncates first, so the demo reset
    endpoint is just this function.
    """
    fixtures_dir = fixtures_dir or FIXTURES_DIR
    required = ["traces.json", "outcomes.json", "configs.json", "runaway_trace.json"]
    missing = [f for f in required if not (fixtures_dir / f).exists()]
    if missing:
        raise DataError(
            f"missing fixtures {missing} in {fixtures_dir}. "
            "Run `python -m harness.record_runs` to produce them."
        )

    init_schema(conn)
    conn.execute("DELETE FROM traces")
    conn.execute("DELETE FROM outcomes")
    conn.execute("DELETE FROM configs")

    traces = json.loads((fixtures_dir / "traces.json").read_text())
    outcomes = json.loads((fixtures_dir / "outcomes.json").read_text())
    configs = json.loads((fixtures_dir / "configs.json").read_text())
    runaway = json.loads((fixtures_dir / "runaway_trace.json").read_text())

    n_t = _insert_many(conn, "traces", TRACE_COLUMNS, traces)
    n_t += _insert_many(conn, "traces", TRACE_COLUMNS, runaway["spans"])
    n_o = _insert_many(conn, "outcomes", OUTCOME_COLUMNS, outcomes)
    n_c = _insert_many(
        conn, "configs",
        ("config_id", "use_case", "label", "role", "ablated_stage", "levers", "recorded_at"),
        configs,
    )
    conn.commit()
    return {"traces": n_t, "outcomes": n_o, "configs": n_c}


def init_schema_if_needed(conn: sqlite3.Connection) -> None:
    init_schema(conn)


def upsert_traces(conn: sqlite3.Connection, rows: list[dict]) -> int:
    return _insert_many(conn, "traces", TRACE_COLUMNS, rows)


def upsert_outcomes(conn: sqlite3.Connection, rows: list[dict]) -> int:
    return _insert_many(conn, "outcomes", OUTCOME_COLUMNS, rows)


def upsert_configs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    return _insert_many(
        conn, "configs",
        ("config_id", "use_case", "label", "role", "ablated_stage", "levers", "recorded_at"),
        rows,
    )


def ensure_seeded(conn: sqlite3.Connection) -> None:
    init_schema(conn)
    if is_empty(conn):
        seed_from_fixtures(conn)


# --- reads -------------------------------------------------------------------
def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def manifest(conn: sqlite3.Connection, fixtures_dir: Path | None = None) -> dict[str, Any]:
    path = (fixtures_dir or FIXTURES_DIR) / "manifest.json"
    base = json.loads(path.read_text()) if path.exists() else {}
    base["rows_in_store"] = {
        "traces": conn.execute("SELECT COUNT(*) c FROM traces").fetchone()["c"],
        "outcomes": conn.execute("SELECT COUNT(*) c FROM outcomes").fetchone()["c"],
    }
    return base


def list_configs(conn: sqlite3.Connection, use_case: str | None = None) -> list[dict]:
    sql = "SELECT * FROM configs"
    params: tuple = ()
    if use_case:
        sql += " WHERE use_case = ?"
        params = (use_case,)
    out = _rows(conn, sql + " ORDER BY role DESC, config_id", params)
    for row in out:
        row["levers"] = json.loads(row["levers"])
    return out


def spans_for_config(conn: sqlite3.Connection, use_case: str, config_id: str,
                     environment: str = "eval") -> list[dict]:
    rows = _rows(
        conn,
        "SELECT * FROM traces WHERE use_case = ? AND config_id = ? AND environment = ?",
        (use_case, config_id, environment),
    )
    if not rows:
        raise DataError(
            f"no recorded spans for config '{config_id}' ({use_case}/{environment}). "
            "A configuration with no recorded runs has no measured cost — refusing "
            "to report one."
        )
    return rows


def outcomes_for_config(conn: sqlite3.Connection, use_case: str, config_id: str,
                        environment: str = "eval") -> list[dict]:
    rows = _rows(
        conn,
        "SELECT * FROM outcomes WHERE use_case = ? AND config_id = ? AND environment = ?",
        (use_case, config_id, environment),
    )
    if not rows:
        raise DataError(
            f"no recorded outcomes for config '{config_id}' ({use_case}/{environment})."
        )
    for row in rows:
        row["quality_scores"] = json.loads(row["quality_scores"])
        row["succeeded"] = bool(row["succeeded"])
    return rows


def production_spans(conn: sqlite3.Connection, use_case: str | None = None) -> list[dict]:
    sql = "SELECT * FROM traces WHERE environment IN ('production', 'ci')"
    params: tuple = ()
    if use_case:
        sql += " AND use_case = ?"
        params = (use_case,)
    return _rows(conn, sql, params)


def production_outcomes(conn: sqlite3.Connection, use_case: str | None = None) -> list[dict]:
    sql = "SELECT * FROM outcomes WHERE environment = 'production'"
    params: tuple = ()
    if use_case:
        sql += " AND use_case = ?"
        params = (use_case,)
    rows = _rows(conn, sql, params)
    for row in rows:
        row["quality_scores"] = json.loads(row["quality_scores"])
        row["succeeded"] = bool(row["succeeded"])
    return rows


def trace_spans(conn: sqlite3.Connection, trace_id: str) -> list[dict]:
    rows = _rows(conn, "SELECT * FROM traces WHERE trace_id = ? ORDER BY started_at, span_id",
                 (trace_id,))
    if not rows:
        raise DataError(f"no spans recorded for trace '{trace_id}'")
    return rows


def find_runaway_trace_id(conn: sqlite3.Connection, use_case: str | None = None) -> str:
    """
    The trace worth replaying: the most expensive one on record for the use case.

    Deliberately not a lookup for a known demo id. Whichever workload is loaded,
    the breaker page opens on that workload's worst real trace — which is the
    only version of this screen anyone would trust.
    """
    sql = """
        SELECT trace_id, SUM(cost_usd) AS total
        FROM traces
        WHERE environment = 'production'
        {filter}
        GROUP BY trace_id
        ORDER BY total DESC
        LIMIT 1
    """.format(filter="AND use_case = ?" if use_case else "")
    row = conn.execute(sql, (use_case,) if use_case else ()).fetchone()
    if row is None:
        raise DataError(
            f"no production traces recorded{f' for {use_case}' if use_case else ''}; "
            "there is nothing to replay"
        )
    return row["trace_id"]


__all__ = [
    "DataError", "connect", "ensure_seeded", "seed_from_fixtures", "manifest",
    "list_configs", "spans_for_config", "outcomes_for_config", "production_spans",
    "production_outcomes", "trace_spans", "find_runaway_trace_id",
    "init_schema_if_needed", "upsert_traces", "upsert_outcomes", "upsert_configs",
]
