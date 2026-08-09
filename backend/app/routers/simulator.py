"""MODULE 4 endpoints — the optimisation simulator. Everything here is projected."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.policy import use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.service.measurement import compute_baseline, evaluate_candidate, promotion_decision
from app.service.simulator import catalogue, simulate

router = APIRouter(prefix="/api/v1/simulate", tags=["module-4"])


class SimulateRequest(BaseModel):
    use_case: str = "contract_analysis"
    levers: dict[str, Any] = Field(default_factory=dict)
    environment: str = "eval"


def _baseline_pack(conn: sqlite3.Connection, use_case: str, environment: str):
    configs = guard(store.list_configs, conn, use_case)
    base_cfg = next((c for c in configs if c["role"] == "baseline"), None)
    if base_cfg is None:
        raise_no_baseline(use_case)
    spans = guard(store.spans_for_config, conn, use_case, base_cfg["config_id"], environment)
    outcomes = guard(store.outcomes_for_config, conn, use_case, base_cfg["config_id"], environment)
    return base_cfg, compute_baseline(spans, outcomes, base_cfg["config_id"], base_cfg["label"]), \
        outcomes, configs


def raise_no_baseline(use_case: str):
    raise store.DataError(f"no baseline configuration recorded for '{use_case}'")


def _measured_candidates(conn, use_case, environment, configs, base, base_outcomes):
    """Recorded configurations, so a projection can be put beside a measurement."""
    policy = guard(use_case_policy, use_case)
    out = []
    for cfg in configs:
        if cfg["role"] not in ("candidate", "baseline"):
            continue
        spans = guard(store.spans_for_config, conn, use_case, cfg["config_id"], environment)
        outcomes = guard(store.outcomes_for_config, conn, use_case, cfg["config_id"], environment)
        measured = compute_baseline(spans, outcomes, cfg["config_id"], cfg["label"])
        decision = "baseline"
        if cfg["role"] == "candidate":
            comparison = guard(evaluate_candidate, base, measured, base_outcomes, outcomes)
            decision = guard(promotion_decision, base, measured, policy, comparison)["decision"]
        out.append({
            "config_id": cfg["config_id"],
            "label": cfg["label"],
            "levers": cfg["levers"],
            "measured": measured,
            "decision": decision,
        })
    return out


@router.get("/levers")
def levers(conn: sqlite3.Connection = Conn,
           use_case: str = Query(default="contract_analysis"),
           environment: str = Query(default="eval")) -> dict[str, Any]:
    base_cfg, base, base_outcomes, configs = _baseline_pack(conn, use_case, environment)
    measured = _measured_candidates(conn, use_case, environment, configs, base, base_outcomes)
    return guard(
        catalogue,
        base_cfg["config_id"],
        {
            m["config_id"]: {
                "label": m["label"],
                "levers": m["levers"],
                "cost_per_document_usd": m["measured"]["cost_per_document_usd"],
                "quality": m["measured"]["quality"],
                "latency_p95_ms": m["measured"]["latency_ms"]["p95"],
                "decision": m["decision"],
            }
            for m in measured
        },
    )


@router.post("")
def simulate_endpoint(req: SimulateRequest, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    policy = guard(use_case_policy, req.use_case)
    base_cfg, base, base_outcomes, configs = _baseline_pack(conn, req.use_case, req.environment)
    measured = _measured_candidates(conn, req.use_case, req.environment, configs, base,
                                    base_outcomes)

    # Monthly volume comes from the recorded production stream, not from a guess.
    prod = [s for s in guard(store.production_spans, conn, req.use_case)
            if s["environment"] == "production"]
    days = len({s["started_at"][:10] for s in prod})
    docs = len({s["doc_id"] for s in prod if s.get("doc_id")})
    monthly_documents = docs / days * 30 if days else 0

    result = guard(simulate, base, req.levers, policy, monthly_documents, measured)
    result["use_case"] = req.use_case
    result["monthly_documents_basis"] = round(monthly_documents, 1)
    return result
