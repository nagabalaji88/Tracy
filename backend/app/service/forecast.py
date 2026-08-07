"""
MODULE 3 — driver-based forecast and budget governor.

A trend line through aggregate spend is the wrong model twice over.

First, spend is a product of drivers that move independently:

    spend = volume x tokens_per_call x retry_factor x fan_out x price

Each driver has its own distribution and its own reason to change. Volume jumps
when a tenant onboards; tokens_per_call jumps when someone edits a prompt; the
retry factor jumps when a schema changes. Fitting one line through the product
of four things loses every one of those signals.

Second, a point forecast is not a budget input. What a finance team needs is p50,
p95, and the reserve between them.

And a prompt deploy is a regime change, not a data point. The forecaster fits
only the current regime and marks every deploy on the history.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from app.service.measurement import MeasurementError
from app.service.stats import lognormal_fit, mean, percentile

SIMULATIONS = 4000
SEED = 20260807

# Only these buckets scale with business volume. Index rebuilds and CI runs are
# real money and are attributed in Module 2, but they are batch events triggered
# by deploys — folding them into a volume-driven forecast models the wrong thing,
# and a single 3M-token reindex span wrecks the tokens-per-call driver.
VOLUME_DRIVEN_BUCKETS = frozenset({"inference", "retry", "tool"})


def split_incidents(spans: Sequence[dict], max_usd_per_trace: float
                    ) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """
    Separate ordinary traffic from incident traces.

    An incident is defined by policy, not by eyeballing the chart: any trace whose
    total cost exceeds the `max_usd_per_trace` circuit breaker. Incidents are real
    spend and are never hidden — but they are not a driver, and fitting a demand
    forecast through one runaway agent loop would project a recurring cost that
    has no recurring cause.
    """
    by_trace: dict[str, float] = defaultdict(float)
    for span in spans:
        by_trace[span["trace_id"]] += span["cost_usd"]
    incident_ids = {t for t, cost in by_trace.items() if cost > max_usd_per_trace}

    normal = [s for s in spans if s["trace_id"] not in incident_ids]
    incidents = [s for s in spans if s["trace_id"] in incident_ids]
    summary = {
        "n_traces": len(incident_ids),
        "trace_ids": sorted(incident_ids),
        "spend_usd": round(sum(s["cost_usd"] for s in incidents), 2),
        "threshold_usd": max_usd_per_trace,
        "note": (
            "Traces above the per-trace circuit-breaker limit. Counted in spend, "
            "excluded from the driver fit: an incident is not demand."
        ),
    }
    return normal, incidents, summary


def _day(iso: str) -> str:
    return iso[:10]


def daily_history(spans: Sequence[dict]) -> list[dict[str, Any]]:
    """One row per day: spend, documents, calls, tokens, retries, prompt version."""
    if not spans:
        raise MeasurementError("no spans; there is no history to forecast from")
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "spend_usd": 0.0, "documents": set(), "calls": 0, "retries": 0,
            "input_tokens": 0, "output_tokens": 0, "prompt_versions": defaultdict(int),
        }
    )
    for span in spans:
        d = days[_day(span["started_at"])]
        d["spend_usd"] += span["cost_usd"]
        if span.get("doc_id"):
            d["documents"].add(span["doc_id"])
        d["calls"] += 1
        if span["retry_index"] > 0:
            d["retries"] += 1
        d["input_tokens"] += span["input_tokens_fresh"] + span["input_tokens_cached"]
        d["output_tokens"] += span["output_tokens"] + span["reasoning_tokens"]
        d["prompt_versions"][span["prompt_version"]] += 1

    rows = []
    for day in sorted(days):
        d = days[day]
        n_docs = len(d["documents"])
        first_attempts = d["calls"] - d["retries"]
        rows.append({
            "date": day,
            "spend_usd": round(d["spend_usd"], 4),
            "documents": n_docs,
            "calls": d["calls"],
            "retries": d["retries"],
            "tokens_per_call": round(
                (d["input_tokens"] + d["output_tokens"]) / d["calls"], 1) if d["calls"] else 0.0,
            "retry_factor": round(d["calls"] / first_attempts, 4) if first_attempts else 1.0,
            "fan_out": round(d["calls"] / n_docs, 3) if n_docs else 0.0,
            "cost_per_document_usd": round(d["spend_usd"] / n_docs, 5) if n_docs else 0.0,
            "prompt_version": max(d["prompt_versions"].items(), key=lambda kv: kv[1])[0],
        })
    return rows


def change_points(history: Sequence[dict]) -> list[dict[str, Any]]:
    """
    Every prompt-version deploy, with the shift in daily spend across it.

    These are not anomalies to smooth away. They are the boundaries between
    regimes, and the forecaster refuses to fit across them.
    """
    points = []
    for i, row in enumerate(history):
        if i == 0 or row["prompt_version"] == history[i - 1]["prompt_version"]:
            continue
        before = [r["spend_usd"] for r in history[max(0, i - 7):i]]
        after = [r["spend_usd"] for r in history[i:i + 7]]
        b = mean(before) if before else 0.0
        a = mean(after) if after else 0.0
        points.append({
            "date": row["date"],
            "prompt_version": row["prompt_version"],
            "day_index": i,
            "spend_before": round(b, 3),
            "spend_after": round(a, 3),
            "pct_change": round((a - b) / b * 100, 1) if b else None,
        })
    return points


def _driver_samples(history: Sequence[dict], key: str) -> list[float]:
    return [float(r[key]) for r in history if r[key] > 0]


def _project_driver(name: str, label: str, unit: str, samples: Sequence[float],
                    note: str) -> dict[str, Any]:
    """
    Fit each driver separately, on the current regime only.

    Volume and tokens-per-call are positive and right-skewed, so a lognormal is
    the honest default; the retry factor is bounded near 1 and is projected
    empirically. Either way the driver keeps its own distribution instead of
    being averaged into the aggregate.
    """
    if len(samples) < 3:
        raise MeasurementError(
            f"driver '{name}' has {len(samples)} observations in the current regime; "
            "refusing to project from that. Wait for more days or widen the regime."
        )
    fit = lognormal_fit(samples)
    return {
        "name": name,
        "label": label,
        "unit": unit,
        "current": round(samples[-1], 4),
        "mean": round(mean(samples), 4),
        "p50": round(math.exp(fit["mu"]), 4),
        "p95": round(math.exp(fit["mu"] + 1.645 * fit["sigma"]), 4),
        "sigma": round(fit["sigma"], 4),
        "n": fit["n"],
        "method": "lognormal fit on the current regime",
        "note": note,
    }


def forecast(
    spans: Sequence[dict],
    horizon_days: int,
    budget_usd: float,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Monte Carlo over the drivers, not over the aggregate.

    Each simulated day draws volume, tokens-per-call, retry factor and fan-out
    independently, then multiplies them by the measured cost per thousand tokens.
    The result is a distribution; p50 and p95 both come out of it, and the gap
    between them is the tail reserve.
    """
    history = daily_history(spans)
    if len(history) < 7:
        raise MeasurementError(
            f"only {len(history)} days of history; refusing to forecast a month from that"
        )
    points = change_points(history)

    # Fit the CURRENT regime only. A prompt edit changes the token economics, so
    # data from before the last deploy describes a system that no longer exists.
    regime_start = points[-1]["day_index"] if points else 0
    regime = history[regime_start:]
    if len(regime) < 5:
        regime = history[-max(7, len(history) // 4):]
        regime_note = (
            "The current regime is younger than 5 days, so the projection falls back to "
            "the most recent window. Treat the interval as wide."
        )
    else:
        regime_note = (
            f"Fitted on {len(regime)} days since the "
            f"{regime[0]['prompt_version']} deploy. Data from earlier regimes is excluded, "
            "not smoothed."
        )

    drivers = [
        _project_driver("volume", "Documents per day", "docs/day",
                        _driver_samples(regime, "documents"),
                        "Business demand. Moves when a tenant onboards, not when you change code."),
        _project_driver("tokens_per_call", "Tokens per call", "tokens",
                        _driver_samples(regime, "tokens_per_call"),
                        "Prompt and context size. Every prompt edit resets this."),
        _project_driver("retry_factor", "Retry factor", "calls/first attempt",
                        _driver_samples(regime, "retry_factor"),
                        "Structured-output failures. A schema change moves it, silently."),
        _project_driver("fan_out", "Fan-out", "calls/document",
                        _driver_samples(regime, "fan_out"),
                        "Agent stages per document. Adding a stage multiplies everything downstream."),
    ]

    # Price per token, measured over the regime rather than assumed.
    regime_tokens = sum(r["tokens_per_call"] * r["calls"] for r in regime)
    regime_spend = sum(r["spend_usd"] for r in regime)
    if regime_tokens <= 0:
        raise MeasurementError("no tokens recorded in the current regime; cannot price a forecast")
    usd_per_token = regime_spend / regime_tokens

    fits = {d["name"]: d for d in drivers}
    rng = random.Random(SEED)

    def draw(name: str) -> float:
        d = fits[name]
        mu = math.log(d["p50"])
        return math.exp(rng.gauss(mu, d["sigma"]))

    today = today or date.fromisoformat(history[-1]["date"])
    daily_totals: list[list[float]] = [[] for _ in range(horizon_days)]
    run_totals: list[float] = []
    for _ in range(SIMULATIONS):
        running = 0.0
        for day_i in range(horizon_days):
            spend = (
                draw("volume") * draw("fan_out") * draw("retry_factor")
                * draw("tokens_per_call") * usd_per_token
            )
            daily_totals[day_i].append(spend)
            running += spend
        run_totals.append(running)

    projection = []
    cum_p50 = cum_p95 = 0.0
    for i, day_samples in enumerate(daily_totals):
        p50 = percentile(day_samples, 50)
        p95 = percentile(day_samples, 95)
        cum_p50 += p50
        cum_p95 += p95
        projection.append({
            "date": (today + timedelta(days=i + 1)).isoformat(),
            "p50_usd": round(p50, 3),
            "p95_usd": round(p95, 3),
            "cumulative_p50_usd": round(cum_p50, 2),
            "cumulative_p95_usd": round(cum_p95, 2),
        })

    horizon_p50 = percentile(run_totals, 50)
    horizon_p95 = percentile(run_totals, 95)

    return {
        "drivers": drivers,
        "history": history,
        "change_points": points,
        "projection": projection,
        "horizon": {
            "days": horizon_days,
            "p50_usd": round(horizon_p50, 2),
            "p95_usd": round(horizon_p95, 2),
            "tail_reserve_usd": round(horizon_p95 - horizon_p50, 2),
        },
        "regime": {
            "since": regime[0]["date"],
            "prompt_version": regime[0]["prompt_version"],
            "days_in_regime": len(regime),
            "note": regime_note,
        },
        "usd_per_token": usd_per_token,
        "simulations": SIMULATIONS,
        "budget_usd": budget_usd,
    }


def month_position(spans: Sequence[dict], today: date, budget_usd: float,
                   fc: dict[str, Any], incident_spans: Sequence[dict] = (),
                   include_incidents: bool = True) -> dict[str, Any]:
    """
    Where the calendar month stands, and where it is heading.

    `include_incidents` decides whether one-off incident spend counts against the
    budget. Both answers are defensible and both are shown: the money left the
    account either way, but "are we overspending on the work?" and "did we
    overspend this month?" are different questions.
    """
    month_prefix = today.strftime("%Y-%m")
    ongoing = sum(s["cost_usd"] for s in spans if s["started_at"].startswith(month_prefix))
    incident = sum(
        s["cost_usd"] for s in incident_spans if s["started_at"].startswith(month_prefix)
    )
    spend_to_date = ongoing + incident if include_incidents else ongoing
    days_elapsed = today.day
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    days_in_month = (next_month - date(today.year, today.month, 1)).days
    days_remaining = days_in_month - days_elapsed

    remaining = [p for p in fc["projection"][:days_remaining]]
    add_p50 = remaining[-1]["cumulative_p50_usd"] if remaining else 0.0
    add_p95 = remaining[-1]["cumulative_p95_usd"] if remaining else 0.0

    p50_total = spend_to_date + add_p50
    p95_total = spend_to_date + add_p95
    return {
        "month": month_prefix,
        "spend_to_date_usd": round(spend_to_date, 2),
        "ongoing_spend_usd": round(ongoing, 2),
        "incident_spend_usd": round(incident, 2),
        "includes_incidents": include_incidents,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "projected_p50_usd": round(p50_total, 2),
        "projected_p95_usd": round(p95_total, 2),
        "budget_usd": budget_usd,
        "tail_reserve_usd": round(p95_total - p50_total, 2),
        "p50_pct_of_budget": round(p50_total / budget_usd * 100, 1),
        "p95_pct_of_budget": round(p95_total / budget_usd * 100, 1),
    }


LADDER_DESCRIPTIONS = {
    "route_cheapest_above_floor": (
        "Route new work to the cheapest recorded configuration that still clears every "
        "quality floor. Not the cheapest configuration — the cheapest one that passed."
    ),
    "queue_to_batch": (
        "Hold non-interactive work for the batch endpoint. Trades latency for roughly half "
        "the token price, and is only offered where the latency ceiling allows it."
    ),
    "reject_with_reason": (
        "Refuse new work and return the budget reason to the caller. A control plane that "
        "cannot say no is a dashboard."
    ),
}


def governor(month: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate the degradation ladder from policy.yaml against current spend.

    Reports the rung that is active now, the next one, and where the projection
    lands — because knowing you will breach on the 22nd is worth more than
    discovering it on the 22nd.
    """
    if "degradation_ladder" not in policy:
        raise MeasurementError("the use-case policy declares no degradation ladder")
    budget = float(policy["monthly_budget_usd"])
    spend = month["spend_to_date_usd"]
    pct_now = spend / budget * 100

    rungs = sorted(policy["degradation_ladder"], key=lambda r: r["at_pct"])
    ladder = []
    active = None
    nxt = None
    for rung in rungs:
        threshold = budget * rung["at_pct"] / 100
        state = "active" if pct_now >= rung["at_pct"] else "pending"
        entry = {
            "at_pct": rung["at_pct"],
            "action": rung["action"],
            "description": LADDER_DESCRIPTIONS.get(rung["action"], ""),
            "threshold_usd": round(threshold, 2),
            "state": state,
        }
        ladder.append(entry)
        if state == "active":
            active = entry
        elif nxt is None:
            nxt = dict(entry)
            nxt["usd_until"] = round(threshold - spend, 2)
            # When does the p50 path cross this rung?
            nxt["projected_date"] = None

    def rung_for(total: float) -> int | None:
        crossed = [r["at_pct"] for r in rungs if total / budget * 100 >= r["at_pct"]]
        return max(crossed) if crossed else None

    return {
        "budget_usd": budget,
        "spend_to_date_usd": round(spend, 2),
        "pct_of_budget": round(pct_now, 1),
        "active_rung": active,
        "next_rung": nxt,
        "ladder": ladder,
        "projected_end_of_month": {
            "p50_usd": month["projected_p50_usd"],
            "p95_usd": month["projected_p95_usd"],
            "p50_rung": rung_for(month["projected_p50_usd"]),
            "p95_rung": rung_for(month["projected_p95_usd"]),
        },
    }


def crossing_date(spend_to_date: float, threshold: float,
                  projection: Sequence[dict], today: date) -> str | None:
    """First projected date at which cumulative p50 spend crosses a threshold."""
    for i, row in enumerate(projection):
        if spend_to_date + row["cumulative_p50_usd"] >= threshold:
            return (today + timedelta(days=i + 1)).isoformat()
    return None


def parse_today(spans: Sequence[dict]) -> date:
    """'Now' is the latest recorded span. A demo must not drift with wall clock."""
    if not spans:
        raise MeasurementError("no spans; cannot establish the current date from the store")
    latest = max(s["started_at"] for s in spans)
    return datetime.fromisoformat(latest).date()
