"""
Ingest — the seam an external agent arrives through.

One POST endpoint per adapter. The adapter does the mapping; this router does
transport and persistence, and nothing else. Adding a second external agent adds
a second adapter and a second route of this size.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.adapters import atlas
from app.policy import use_case_policy
from app.repository import store
from app.routers.deps import Conn, guard
from app.schema_def import OUTCOME_COLUMNS, TRACE_COLUMNS

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


class AtlasPayload(BaseModel):
    source: str = "atlas"
    schema_version: str = Field(default="atlas.debug_record/v1", alias="schema")
    runs: list[dict[str, Any]]

    model_config = {"populate_by_name": True}


@router.get("/atlas/golden-set")
def golden_set() -> dict[str, Any]:
    """
    The evaluation corpus, declared in policy.yaml.

    ATLAS calls this to find out what to run. The agent has no golden set of its
    own — supplying one is part of what onboarding means.
    """
    policy = guard(use_case_policy, atlas.USE_CASE)
    if "golden_set" not in policy:
        return guard(_no_golden_set)
    gs = policy["golden_set"]
    return {
        "use_case": atlas.USE_CASE,
        "subjects": gs["subjects"],
        "source": gs.get("source"),
        "note": gs.get("note"),
        "quality_floor": policy["quality_floor"],
        "latency_ceiling_ms": policy["latency_ceiling_ms"],
    }


@router.post("/atlas")
def ingest_atlas(payload: AtlasPayload, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """
    Accept ATLAS debug records and map them onto the spine.

    Idempotent: span and outcome ids come from ATLAS run ids, so re-posting the
    same batch replaces rather than duplicates.
    """
    mapped = guard(atlas.ingest_records, payload.runs)

    def write() -> dict[str, int]:
        store.init_schema_if_needed(conn)
        n_t = store.upsert_traces(conn, mapped["traces"])
        n_o = store.upsert_outcomes(conn, mapped["outcomes"])
        n_c = store.upsert_configs(conn, mapped["configs"])
        conn.commit()
        return {"traces": n_t, "outcomes": n_o, "configs": n_c}

    written = guard(write)
    policy = guard(use_case_policy, atlas.USE_CASE)
    return {
        "ingested": written,
        "runs": len(payload.runs),
        "batch": atlas.digest(payload.runs),
        "use_case": atlas.USE_CASE,
        "adapter": {"scorer": atlas.ATLAS_SCORER.name, "cost_meter": "token_cost_meter/v1"},
        "policy_applied": {
            "quality_floor": policy["quality_floor"],
            "latency_ceiling_ms": policy["latency_ceiling_ms"],
            "monthly_budget_usd": policy["monthly_budget_usd"],
            "circuit_breakers": policy["circuit_breakers"],
        },
        "columns": {"trace": len(TRACE_COLUMNS), "outcome": len(OUTCOME_COLUMNS)},
        "next": [
            "GET /api/v1/measurement/board?use_case=equity_research_memo",
            "GET /api/v1/attribution/rollup?use_case=equity_research_memo",
            "GET /api/v1/forecast?use_case=equity_research_memo",
            "GET /api/v1/breakers/replay?use_case=equity_research_memo",
            "GET /api/v1/executive?use_case=equity_research_memo",
        ],
    }


def _no_golden_set():
    raise store.DataError(
        f"policy.yaml declares no golden_set for '{atlas.USE_CASE}'. An agent with no "
        "evaluation corpus cannot be evaluated — declare one before ingesting."
    )
