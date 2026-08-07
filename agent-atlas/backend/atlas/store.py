"""
Run persistence.

Two surfaces, and the gap between them is the point.

`runs/<run_id>.json` is the DEBUG record: every span, every retry, every
artifact. Engineering added it during an incident and it has been written ever
since.

`cost_report()` is the REPORTING surface: what the monthly review sees. One
total, one estimate, no dimension to slice on, no notion of whether any of it
produced work anyone could use.

Nothing in ATLAS joins the first to the second. That join is what a control
plane is for.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
MONTHLY_BUDGET_USD = 3_000.0  # F08 — a constant, checked in a report that runs overnight


def save(record: dict[str, Any]) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def load_all() -> list[dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for path in sorted(RUNS_DIR.glob("ATL-*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda r: r["started_at"], reverse=True)


def load(run_id: str) -> dict[str, Any]:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise KeyError(run_id)
    return json.loads(path.read_text())


def clear() -> int:
    if not RUNS_DIR.exists():
        return 0
    paths = list(RUNS_DIR.glob("ATL-*.json"))
    for path in paths:
        path.unlink()
    return len(paths)


def run_list() -> list[dict[str, Any]]:
    """The history table in the ATLAS UI. Deliberately thin — this is all it has."""
    return [
        {
            "run_id": r["run_id"],
            "ticker": r["ticker"],
            "issuer": r["issuer"],
            "profile_label": r["profile_label"],
            "started_at": r["started_at"],
            "elapsed_s": r["elapsed_s"],
            "status": r["status"],
            "total_tokens": r["total_tokens"],
            "estimated_cost_usd": r["estimated_cost_usd"],
            "llm_calls": len(r["spans"]),
        }
        for r in load_all()
    ]


def cost_report() -> dict[str, Any]:
    """
    THE MONTHLY COST REPORT.

    This is the entire financial visibility ATLAS has. Note what is not here:
    no split by desk, mandate, stage or model; no cost per successful memo,
    because there is no notion of a successful memo; no velocity, because the
    report runs once a month against a number that moves in seconds.
    """
    runs = load_all()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    mtd = [r for r in runs if r["started_at"][:7] == month]
    spend = round(sum(r["estimated_cost_usd"] for r in mtd), 2)
    return {
        "month": month,
        "runs_this_month": len(mtd),
        "estimated_spend_usd": spend,
        "monthly_budget_usd": MONTHLY_BUDGET_USD,
        "pct_of_budget": round(spend / MONTHLY_BUDGET_USD * 100, 1) if MONTHLY_BUDGET_USD else 0,
        "status": "OVER BUDGET" if spend > MONTHLY_BUDGET_USD else "WITHIN BUDGET",
        "rate_note": "Estimated at a flat $0.004 per 1k tokens across all models.",
        "generated": "Overnight batch, 02:00 local.",
        "known_gaps": [
            "No breakdown by desk, mandate, stage or model.",
            "No cost per successful memo — completion is the only outcome recorded.",
            "Retries inside a stage are counted in tokens but not identified.",
            "Cache reads, if there were any, would be priced as fresh input.",
            "A single runaway request can exhaust the month before this report runs.",
        ],
    }
