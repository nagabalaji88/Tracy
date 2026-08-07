"""MODULE 2 endpoints — attribution and cost explorer."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.policy import use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.service.attribution import heavy_tail, rollup, stage_economics

router = APIRouter(prefix="/api/v1/attribution", tags=["module-2"])


@router.get("/rollup")
def rollup_endpoint(conn: sqlite3.Connection = Conn,
                    use_case: str | None = Query(default=None)) -> dict[str, Any]:
    """
    Spend by team / use case / stage / prompt version / model, over production
    and CI traffic. Pass no use_case to see every workload the plane governs.
    """
    spans = guard(store.production_spans, conn, use_case)
    outcomes = guard(store.production_outcomes, conn, use_case)
    result = guard(rollup, spans, outcomes)
    result["use_case"] = use_case or "all"
    return result


@router.get("/stage-economics")
def stage_economics_endpoint(conn: sqlite3.Connection = Conn,
                             use_case: str = Query(default="contract_analysis"),
                             environment: str = Query(default="eval")) -> dict[str, Any]:
    """Is Agent 3 worth what it costs? Answered from recorded ablation runs."""
    configs = guard(store.list_configs, conn, use_case)
    baseline = next((c for c in configs if c["role"] == "baseline"), None)
    if baseline is None:
        return guard(_no_baseline, use_case)

    b_spans = guard(store.spans_for_config, conn, use_case, baseline["config_id"], environment)
    b_outcomes = guard(store.outcomes_for_config, conn, use_case, baseline["config_id"], environment)

    ablations: dict[str, tuple[list[dict], list[dict]]] = {}
    for cfg in configs:
        if cfg["role"] != "ablation" or not cfg["ablated_stage"]:
            continue
        ablations[cfg["ablated_stage"]] = (
            guard(store.spans_for_config, conn, use_case, cfg["config_id"], environment),
            guard(store.outcomes_for_config, conn, use_case, cfg["config_id"], environment),
        )

    policy = guard(use_case_policy, use_case)
    primary_metric = next(iter(policy["quality_floor"]))
    result = guard(stage_economics, b_spans, b_outcomes, ablations, primary_metric,
                   ["clause_extract"])
    result["use_case"] = use_case
    return result


@router.get("/heavy-tail")
def heavy_tail_endpoint(conn: sqlite3.Connection = Conn,
                        use_case: str = Query(default="contract_analysis")) -> dict[str, Any]:
    """p50 / p95 / p99 cost per document, and what the worst 5% consumes."""
    spans = [s for s in guard(store.production_spans, conn, use_case)
             if s["environment"] == "production"]
    outcomes = guard(store.production_outcomes, conn, use_case)
    result = guard(heavy_tail, spans, outcomes)
    result["use_case"] = use_case
    return result


def _no_baseline(use_case: str):
    raise store.DataError(f"no baseline configuration recorded for '{use_case}'")
