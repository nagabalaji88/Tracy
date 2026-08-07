"""
MODULE 6 — the executive view.

One strip of numbers. The headline is cost per successful outcome, because that
is the number the FinOps Foundation says matters and the one no shipping product
computes.

The line that makes this a control plane rather than a dashboard is
`savings_rejected_usd`: money the system could have saved and refused to, with
the floor that caused the refusal attached. A tool that only reports savings
realised cannot be trusted about savings at all.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.service.measurement import MeasurementError, cost_per_successful_outcome


def executive_summary(
    production_spans: Sequence[dict],
    production_outcomes: Sequence[dict],
    decisions: Sequence[dict[str, Any]],
    monthly_documents: float,
    governor: dict[str, Any],
) -> dict[str, Any]:
    """
    `decisions` is one entry per evaluated candidate:
        {config_id, label, decision, headline, cost_delta_pct, cost_saving_usd,
         per_document_saving_usd, failed_floor}
    """
    if not production_spans:
        raise MeasurementError("no production spans; there is no executive view to render")
    if not production_outcomes:
        raise MeasurementError("no production outcomes; cost per successful outcome is undefined")

    total_spend = sum(s["cost_usd"] for s in production_spans)
    n_docs = len({s["doc_id"] for s in production_spans if s.get("doc_id")})
    cpso = cost_per_successful_outcome(total_spend, production_outcomes)

    # Annualised at the measured production volume, so "savings" is a number
    # someone could actually put in a plan rather than a percentage.
    realised = 0.0
    rejected = 0.0
    rows = []
    for d in decisions:
        annualised = -d["per_document_saving_usd"] * monthly_documents * 12
        if d["decision"] == "PROMOTE":
            realised += annualised
        else:
            rejected += annualised
        rows.append({
            "config_id": d["config_id"],
            "label": d["label"],
            "decision": d["decision"],
            "headline": d["headline"],
            "cost_delta_pct": d["cost_delta_pct"],
            "annualised_usd": round(annualised, 2),
            "failed_floor": d.get("failed_floor"),
        })

    dates = sorted(s["started_at"] for s in production_spans)
    return {
        "window": {"from": dates[0], "to": dates[-1], "days": len({d[:10] for d in dates})},
        "kpis": {
            # The headline. Everything else on this strip is supporting evidence.
            "cost_per_successful_outcome_usd": cpso["value_usd"],
            "cost_per_call_usd": round(total_spend / len(production_spans), 6),
            "cost_per_document_usd": round(total_spend / n_docs, 5) if n_docs else None,
            "total_spend_usd": round(total_spend, 2),
            "savings_realised_usd": round(realised, 2),
            # The line that distinguishes a control plane from a dashboard.
            "savings_rejected_usd": round(rejected, 2),
            "success_rate": cpso["success_rate"],
            "rework_hours": round(cpso["rework_minutes"] / 60, 1),
            "rework_usd": cpso["rework_usd"],
            "documents": n_docs,
        },
        "active_rung": governor.get("active_rung"),
        "budget": {
            "budget_usd": governor["budget_usd"],
            "spend_to_date_usd": governor["spend_to_date_usd"],
            "pct_of_budget": governor["pct_of_budget"],
        },
        "decisions": rows,
        "basis": {
            "monthly_documents": round(monthly_documents, 1),
            "annualisation": (
                "Per-document saving x measured monthly document volume x 12. Volume comes "
                "from the recorded production stream, not from a target."
            ),
        },
    }
