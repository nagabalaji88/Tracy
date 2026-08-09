"""MODULE 1 endpoints — measurement core and promotion engine."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.adapters import registered
from app.policy import load_policy, use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.schemas.measurement import BoardResponse, EvaluateRequest, EvaluationResponse
from app.schema_def import EXTENSIONS, OTEL_MAPPING, TRACE_COLUMNS
from app.service.measurement import compute_baseline, evaluate_candidate, promotion_decision

router = APIRouter(prefix="/api/v1", tags=["module-1"])


def _pack(conn: sqlite3.Connection, use_case: str, config_id: str, environment: str,
          label: str | None = None) -> tuple[dict, list[dict]]:
    spans = store.spans_for_config(conn, use_case, config_id, environment)
    outcomes = store.outcomes_for_config(conn, use_case, config_id, environment)
    return compute_baseline(spans, outcomes, config_id, label), outcomes


@router.get("/spine")
def spine() -> dict[str, Any]:
    """The schema, as a public contract. This is what makes it a framework."""
    return {
        "trace_columns": list(TRACE_COLUMNS),
        "otel_genai_mapping": OTEL_MAPPING,
        "extensions": EXTENSIONS,
        "adapters": registered(),
        "policy": load_policy(),
    }


@router.get("/configs")
def configs(conn: sqlite3.Connection = Conn,
            use_case: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return guard(store.list_configs, conn, use_case)


@router.get("/measurement/baseline")
def baseline(conn: sqlite3.Connection = Conn,
             use_case: str = Query(...),
             config_id: str = Query(...),
             environment: str = Query(default="eval")) -> dict[str, Any]:
    pack, _ = guard(_pack, conn, use_case, config_id, environment)
    return pack


@router.post("/measurement/evaluate", response_model=EvaluationResponse)
def evaluate(req: EvaluateRequest, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    policy = guard(use_case_policy, req.use_case)
    base, base_outcomes = guard(_pack, conn, req.use_case, req.baseline_config_id, req.environment)
    cand, cand_outcomes = guard(_pack, conn, req.use_case, req.candidate_config_id, req.environment)
    comparison = guard(evaluate_candidate, base, cand, base_outcomes, cand_outcomes)
    decision = guard(promotion_decision, base, cand, policy, comparison)
    return {"baseline": base, "candidate": cand, "comparison": comparison, "decision": decision}


@router.get("/measurement/board", response_model=BoardResponse)
def board(conn: sqlite3.Connection = Conn,
          use_case: str = Query(default="contract_analysis"),
          environment: str = Query(default="eval")) -> dict[str, Any]:
    """
    The hero screen in one call: baseline plus every recorded candidate, each
    with its paired comparison and its promotion decision.
    """
    policy = guard(use_case_policy, use_case)
    all_configs = guard(store.list_configs, conn, use_case)
    baselines = [c for c in all_configs if c["role"] == "baseline"]
    if not baselines:
        return guard(_missing_baseline, use_case)
    base_cfg = baselines[0]
    base, base_outcomes = guard(_pack, conn, use_case, base_cfg["config_id"], environment,
                                base_cfg["label"])

    candidates = []
    for cfg in all_configs:
        if cfg["role"] != "candidate":
            continue
        cand, cand_outcomes = guard(_pack, conn, use_case, cfg["config_id"], environment,
                                    cfg["label"])
        comparison = guard(evaluate_candidate, base, cand, base_outcomes, cand_outcomes)
        decision = guard(promotion_decision, base, cand, policy, comparison)
        candidates.append({
            "config": cfg,
            "measured": cand,
            "comparison": comparison,
            "decision": decision,
        })

    # Cheapest first: the rejected one usually leads, which is the point.
    candidates.sort(key=lambda c: c["measured"]["cost_per_document_usd"])
    return {
        "use_case": use_case,
        "environment": environment,
        "policy": policy,
        "baseline": {"config": base_cfg, "measured": base},
        "candidates": candidates,
        "generated_from": guard(store.manifest, conn),
    }


def _missing_baseline(use_case: str):
    raise store.DataError(f"no configuration with role 'baseline' recorded for '{use_case}'")
