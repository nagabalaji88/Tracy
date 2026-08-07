"""Request-scoped wiring. The only place routers learn about the store."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException

from app.db import connect
from app.repository import store
from app.policy import PolicyError
from app.service.measurement import MeasurementError


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        store.ensure_seeded(conn)
        yield conn
    finally:
        conn.close()


Conn = Depends(get_conn)


def guard(fn, *args, **kwargs):
    """
    Turn a loud domain failure into a loud HTTP failure.

    Fail loudly on missing data is a design rule, not an aspiration: these become
    400s with the domain message intact rather than empty 200s.
    """
    try:
        return fn(*args, **kwargs)
    except (store.DataError, MeasurementError, PolicyError, LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
