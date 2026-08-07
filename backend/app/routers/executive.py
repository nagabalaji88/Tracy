"""MODULE 6 endpoints — executive view, framework description, demo reset."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.adapters import registered
from app.policy import load_policy, load_pricing, reload as reload_policy, use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.schema_def import EXTENSIONS, OTEL_MAPPING, TRACE_COLUMNS
from app.service.executive import executive_summary
from app.service.forecast import (
    VOLUME_DRIVEN_BUCKETS,
    forecast,
    governor,
    month_position,
    parse_today,
    split_incidents,
)
from app.service.measurement import compute_baseline, evaluate_candidate, promotion_decision

router = APIRouter(prefix="/api/v1", tags=["module-6"])


@router.get("/executive")
def executive(conn: sqlite3.Connection = Conn,
              use_case: str = Query(default="contract_analysis"),
              include_incidents: bool = Query(default=True)) -> dict[str, Any]:
    policy = guard(use_case_policy, use_case)

    prod_spans = [s for s in guard(store.production_spans, conn, use_case)
                  if s["environment"] == "production"]
    prod_outcomes = guard(store.production_outcomes, conn, use_case)

    # --- decisions, recomputed rather than remembered
    configs = guard(store.list_configs, conn, use_case)
    base_cfg = next((c for c in configs if c["role"] == "baseline"), None)
    if base_cfg is None:
        raise_no_baseline(use_case)
    base_spans = guard(store.spans_for_config, conn, use_case, base_cfg["config_id"], "eval")
    base_outcomes = guard(store.outcomes_for_config, conn, use_case, base_cfg["config_id"], "eval")
    base = compute_baseline(base_spans, base_outcomes, base_cfg["config_id"], base_cfg["label"])

    decisions = []
    for cfg in configs:
        if cfg["role"] != "candidate":
            continue
        spans = guard(store.spans_for_config, conn, use_case, cfg["config_id"], "eval")
        outcomes = guard(store.outcomes_for_config, conn, use_case, cfg["config_id"], "eval")
        cand = compute_baseline(spans, outcomes, cfg["config_id"], cfg["label"])
        comparison = guard(evaluate_candidate, base, cand, base_outcomes, outcomes)
        decision = guard(promotion_decision, base, cand, policy, comparison)
        decisions.append({
            "config_id": cfg["config_id"],
            "label": cfg["label"],
            "decision": decision["decision"],
            "headline": decision["headline"],
            "cost_delta_pct": decision["cost_delta_pct"],
            "per_document_saving_usd": round(
                cand["cost_per_document_usd"] - base["cost_per_document_usd"], 6),
            "failed_floor": decision["failed_floors"][0] if decision["failed_floors"] else None,
        })

    # --- budget position
    budget = float(policy["monthly_budget_usd"])
    normal, incidents, _ = guard(
        split_incidents, prod_spans, float(policy["circuit_breakers"]["max_usd_per_trace"]))
    drivers_input = [s for s in normal if s["cost_bucket"] in VOLUME_DRIVEN_BUCKETS]
    today = guard(parse_today, prod_spans)
    fc = guard(forecast, drivers_input, 31, budget, today)
    month = guard(month_position, normal, today, budget, fc, incidents, include_incidents)
    gov = guard(governor, month, policy)

    days = len({s["started_at"][:10] for s in prod_spans})
    # One outcome is one unit of business work. Counting distinct doc_ids instead
    # would undercount any workload that revisits the same subject.
    monthly_documents = len(prod_outcomes) / days * 30 if days else 0

    result = guard(executive_summary, prod_spans, prod_outcomes, decisions,
                   monthly_documents, gov)
    result["use_case"] = use_case
    result["generated_at"] = today.isoformat()
    result["provenance"] = guard(store.manifest, conn)
    return result


@router.get("/framework")
def framework() -> dict[str, Any]:
    """
    What a second workload costs to onboard, stated as data rather than a claim.

    A policy entry and two adapter implementations. The list of files that would
    change is empty by construction: the core resolves adapters through a
    registry and reads floors from policy.
    """
    policy = load_policy()
    return {
        "spine": {
            "trace_columns": list(TRACE_COLUMNS),
            "otel_genai_mapping": OTEL_MAPPING,
            "extensions": EXTENSIONS,
        },
        "adapters": registered(),
        "use_cases": {
            name: {
                "label": uc.get("label", name),
                "quality_floor": uc["quality_floor"],
                "latency_ceiling_ms": uc["latency_ceiling_ms"],
                "monthly_budget_usd": uc["monthly_budget_usd"],
            }
            for name, uc in policy["use_cases"].items()
        },
        "metrics": policy["metrics"],
        "economics": policy["economics"],
        "significance": policy["significance"],
        "models_priced": sorted(load_pricing()["models"]),
        "onboarding": {
            "steps": [
                "Add a use_case entry to policy.yaml with its floors, ceiling and budget.",
                "Declare each new quality metric's direction in policy.yaml:metrics.",
                "Implement the Scorer protocol: recorded artifacts in, scores and a success "
                "verdict out. It may only read what was recorded.",
                "Implement or reuse a CostMeter. TokenCostMeter covers anything priced per token.",
                "Register both against the use case. No core file changes.",
            ],
            "core_files_changed": 0,
            "proof": (
                "ATLAS is the hard version of this claim: a seven-stage equity-research agent "
                "built as a separate application, on its own port, with its own store, which "
                "this package neither imports nor is imported by. Onboarding it took one "
                "policy.yaml entry and app/adapters/atlas.py — a Scorer plus a mapping from "
                "its debug records onto the spine. The CostMeter was reused unchanged. "
                "support_triage is the easy version of the same proof."
            ),
            "external_agents": [
                {
                    "name": "ATLAS",
                    "use_case": "equity_research_memo",
                    "relationship": "separate application; no shared code, no shared database",
                    "cost_to_onboard": [
                        "policy.yaml: 1 use_case entry + 2 metric direction declarations",
                        "app/adapters/atlas.py: AtlasScorer + ingest_records",
                        "app/routers/ingest.py: 1 POST route",
                    ],
                    "core_files_changed": 0,
                }
            ],
        },
        "modules": [
            {"id": 1, "name": "Measurement core & promotion engine",
             "does": "Paired evaluation of a candidate against a baseline over the same golden "
                     "set, and a PROMOTE/REJECT decision against declared floors."},
            {"id": 2, "name": "Attribution & cost explorer",
             "does": "Spend by team, stage, prompt version and model; the buckets other tools "
                     "fold away; stage economics from ablation; the heavy tail."},
            {"id": 3, "name": "Forecast & budget governor",
             "does": "Driver-based Monte Carlo with p50/p95 and a tail reserve, fitted on the "
                     "current prompt regime, plus the degradation ladder."},
            {"id": 4, "name": "Optimisation simulator",
             "does": "Projected effect of lever combinations, calibrated single-lever-at-a-time, "
                     "with pre-flight floor checks."},
            {"id": 5, "name": "Circuit breakers",
             "does": "Per-trace spend, spend velocity against a measured baseline, agent depth "
                     "and loop detection, replayed against a recorded incident."},
            {"id": 6, "name": "Executive view",
             "does": "Cost per successful outcome as the headline, and savings rejected for "
                     "quality reasons as a first-class line."},
        ],
    }


@router.post("/admin/reset")
def reset(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """
    Reload the store from the committed fixtures.

    A failed live run cannot kill the demo: this restores the exact recorded
    state, and policy.yaml is re-read at the same time so a policy edit can be
    demonstrated live.
    """
    reload_policy()
    rows = guard(store.seed_from_fixtures, conn)
    return {"status": "reset", "rows": rows}


def raise_no_baseline(use_case: str):
    raise store.DataError(f"no baseline configuration recorded for '{use_case}'")
