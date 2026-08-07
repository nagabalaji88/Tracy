"""MODULE 3 endpoints — forecast and budget governor."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.policy import use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.service.forecast import (
    VOLUME_DRIVEN_BUCKETS,
    crossing_date,
    forecast,
    governor,
    month_position,
    parse_today,
    split_incidents,
)

router = APIRouter(prefix="/api/v1/forecast", tags=["module-3"])


def _prepare(conn: sqlite3.Connection, use_case: str) -> dict[str, Any]:
    """
    Assemble the inputs the forecaster is allowed to see.

    Production traffic only (CI spend is real but is not driven by business
    volume), volume-driven buckets only for the driver fit, and incident traces
    separated out by the policy's own per-trace limit.
    """
    policy = guard(use_case_policy, use_case)
    all_prod = [s for s in guard(store.production_spans, conn, use_case)
                if s["environment"] == "production"]
    max_per_trace = float(policy["circuit_breakers"]["max_usd_per_trace"])
    normal, incidents, incident_summary = guard(split_incidents, all_prod, max_per_trace)
    drivers_input = [s for s in normal if s["cost_bucket"] in VOLUME_DRIVEN_BUCKETS]
    excluded_usd = sum(s["cost_usd"] for s in normal if s["cost_bucket"] not in VOLUME_DRIVEN_BUCKETS)
    return {
        "policy": policy,
        "budget": float(policy["monthly_budget_usd"]),
        "ongoing": normal,
        "incidents": incidents,
        "incident_summary": incident_summary,
        "drivers_input": drivers_input,
        "excluded_batch_usd": round(excluded_usd, 2),
        "today": guard(parse_today, all_prod),
    }


@router.get("")
def forecast_endpoint(conn: sqlite3.Connection = Conn,
                      use_case: str = Query(default="contract_analysis"),
                      horizon_days: int = Query(default=30, ge=1, le=90),
                      include_incidents: bool = Query(default=True)) -> dict[str, Any]:
    ctx = _prepare(conn, use_case)
    fc = guard(forecast, ctx["drivers_input"], horizon_days, ctx["budget"], ctx["today"])
    fc["use_case"] = use_case
    fc["today"] = ctx["today"].isoformat()
    fc["month"] = guard(
        month_position, ctx["ongoing"], ctx["today"], ctx["budget"], fc,
        ctx["incidents"], include_incidents,
    )
    fc["incidents"] = ctx["incident_summary"]
    fc["excluded_from_drivers"] = {
        "batch_spend_usd": ctx["excluded_batch_usd"],
        "note": (
            "Index rebuilds and other deploy-triggered batch work. Attributed in the "
            "cost explorer, excluded here because it does not scale with volume."
        ),
    }
    return fc


@router.get("/governor")
def governor_endpoint(conn: sqlite3.Connection = Conn,
                      use_case: str = Query(default="contract_analysis"),
                      include_incidents: bool = Query(default=True)) -> dict[str, Any]:
    ctx = _prepare(conn, use_case)
    fc = guard(forecast, ctx["drivers_input"], 31, ctx["budget"], ctx["today"])
    month = guard(
        month_position, ctx["ongoing"], ctx["today"], ctx["budget"], fc,
        ctx["incidents"], include_incidents,
    )
    gov = guard(governor, month, ctx["policy"])
    if gov["next_rung"]:
        gov["next_rung"]["projected_date"] = crossing_date(
            month["spend_to_date_usd"], gov["next_rung"]["threshold_usd"],
            fc["projection"], ctx["today"],
        )
    gov["use_case"] = use_case
    gov["today"] = ctx["today"].isoformat()
    gov["month"] = month
    gov["incidents"] = ctx["incident_summary"]
    return gov
