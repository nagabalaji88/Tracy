"""MODULE 5 endpoints — circuit breaker replay."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.policy import use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.service.breakers import replay, trailing_baseline_usd_per_min

router = APIRouter(prefix="/api/v1/breakers", tags=["module-5"])


@router.get("/replay")
def replay_endpoint(conn: sqlite3.Connection = Conn,
                    use_case: str = Query(default="contract_analysis"),
                    trace_id: str | None = Query(default=None)) -> dict[str, Any]:
    """
    Replay a trace through the breakers configured in policy.yaml.

    Defaults to the recorded runaway trace. Pass any trace_id and the same four
    rules are evaluated — the engine has no knowledge of which trace is the demo.
    """
    policy = guard(use_case_policy, use_case)
    tid = trace_id or guard(store.find_runaway_trace_id, conn)
    spans = guard(store.trace_spans, conn, tid)
    all_prod = [s for s in guard(store.production_spans, conn, use_case)
                if s["environment"] == "production"]
    baseline = guard(trailing_baseline_usd_per_min, all_prod, tid)
    result = guard(
        replay, spans, policy["circuit_breakers"], baseline,
        float(policy["monthly_budget_usd"]),
    )
    result["use_case"] = use_case
    result["trace_id"] = tid
    return result
