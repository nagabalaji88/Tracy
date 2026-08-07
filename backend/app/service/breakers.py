"""
MODULE 5 — circuit breakers.

The argument this module has to make: a monthly cap is not a control. A $400
monthly budget permits burning $400 in twenty minutes, and by the time a monthly
number moves the money is gone. Spend needs a derivative control, not just a
level control.

Four breakers, all configured in policy.yaml:

  max_usd_per_trace              a single trace's total cost
  max_spend_velocity_multiplier  burn rate against the trailing baseline
  max_agent_depth                recursion depth
  max_identical_calls            the same call fingerprint, over and over

The engine replays a recorded trace span by span and trips on the first breach.
It is not special-cased to the demo trace: feed it any trace and it will evaluate
the same four rules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Sequence

from app.service.measurement import MeasurementError

BREAKER_LABELS = {
    "max_usd_per_trace": "Per-trace spend limit",
    "max_spend_velocity_multiplier": "Spend velocity",
    "max_agent_depth": "Agent recursion depth",
    "max_identical_calls": "Repeated identical call",
}


def trailing_baseline_usd_per_min(spans: Sequence[dict], exclude_trace_id: str) -> float:
    """
    Normal burn rate, measured from ordinary traffic.

    The velocity breaker is relative: 3x of nothing is nothing, and 3x of normal
    is an incident. That means the baseline has to be measured, not configured.
    """
    ordinary = [s for s in spans if s["trace_id"] != exclude_trace_id]
    if not ordinary:
        raise MeasurementError(
            "no ordinary traffic to establish a trailing baseline; a relative velocity "
            "breaker cannot be evaluated against an empty history"
        )
    per_trace_rate: list[float] = []
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for span in ordinary:
        by_trace[span["trace_id"]].append(span)
    for trace_spans in by_trace.values():
        total = sum(s["cost_usd"] for s in trace_spans)
        duration_min = sum(s["latency_ms"] for s in trace_spans) / 60000.0
        if duration_min > 0:
            per_trace_rate.append(total / duration_min)
    if not per_trace_rate:
        raise MeasurementError("no ordinary trace had a positive duration")
    return sum(per_trace_rate) / len(per_trace_rate)


def replay(
    spans: Sequence[dict],
    breakers: dict[str, Any],
    baseline_usd_per_min: float,
    monthly_cap_usd: float,
) -> dict[str, Any]:
    """
    Replay a trace through the breakers, one span at a time.

    Returns every frame — including the ones after the trip — so the UI can show
    the counterfactual: what was spent before the breaker fired, and what would
    have been spent if nothing had.
    """
    if not spans:
        raise MeasurementError("no spans to replay")
    for required in ("max_usd_per_trace", "max_spend_velocity_multiplier",
                     "max_agent_depth", "max_identical_calls", "velocity_min_window_s"):
        if required not in breakers:
            raise MeasurementError(
                f"policy does not configure the '{required}' breaker; refusing to "
                "replay against an assumed limit"
            )

    ordered = sorted(spans, key=lambda s: (s["started_at"], s["span_id"]))
    start = datetime.fromisoformat(ordered[0]["started_at"])

    cumulative = 0.0
    elapsed_ms = 0
    fingerprints: dict[str, int] = defaultdict(int)
    frames: list[dict[str, Any]] = []
    first_breach: dict[str, dict[str, Any]] = {}
    trip: dict[str, Any] | None = None

    for i, span in enumerate(ordered):
        cumulative += span["cost_usd"]
        elapsed_ms += span["latency_ms"]
        # Wall-clock elapsed, from the recorded timestamps, with the current span's
        # own latency added: the breaker can only act once the call has returned.
        wall_s = (datetime.fromisoformat(span["started_at"]) - start).total_seconds() \
            + span["latency_ms"] / 1000.0
        minutes = max(wall_s / 60.0, 1e-9)
        velocity = cumulative / minutes
        multiplier = velocity / baseline_usd_per_min if baseline_usd_per_min else 0.0
        fingerprints[span["call_fingerprint"]] += 1
        identical = fingerprints[span["call_fingerprint"]]

        # Every breaker is evaluated on every span, and each one's first breach is
        # recorded. Only the earliest actually stops the trace, but showing which
        # others would have caught it — and how much later — is the argument for
        # having more than one.
        velocity_armed = wall_s >= breakers["velocity_min_window_s"]
        breaches: list[tuple[str, str]] = []
        if cumulative > breakers["max_usd_per_trace"]:
            breaches.append((
                "max_usd_per_trace",
                f"trace has spent ${cumulative:.2f}, over the "
                f"${breakers['max_usd_per_trace']:.2f} per-trace limit",
            ))
        if velocity_armed and multiplier > breakers["max_spend_velocity_multiplier"]:
            breaches.append((
                "max_spend_velocity_multiplier",
                f"burning ${velocity:.2f}/min, {multiplier:.1f}x the trailing baseline of "
                f"${baseline_usd_per_min:.2f}/min "
                f"(limit {breakers['max_spend_velocity_multiplier']:.1f}x)",
            ))
        if span["agent_depth"] > breakers["max_agent_depth"]:
            breaches.append((
                "max_agent_depth",
                f"agent recursion reached depth {span['agent_depth']}, over the limit of "
                f"{breakers['max_agent_depth']}",
            ))
        if identical > breakers["max_identical_calls"]:
            breaches.append((
                "max_identical_calls",
                f"call fingerprint {span['call_fingerprint'][:10]} issued {identical} times; "
                f"the limit is {breakers['max_identical_calls']} — this is a loop, not work",
            ))

        for name, detail_text in breaches:
            if name not in first_breach:
                first_breach[name] = {
                    "breaker": name,
                    "label": BREAKER_LABELS[name],
                    "index": i,
                    "detail": detail_text,
                    "spent_usd": round(cumulative, 4),
                    "elapsed_s": round(wall_s, 1),
                }

        tripped = breaches[0][0] if breaches else None
        detail = breaches[0][1] if breaches else ""

        frames.append({
            "index": i,
            "span_id": span["span_id"],
            "stage": span["stage"],
            "model": span["model"],
            "agent_depth": span["agent_depth"],
            "input_tokens": span["input_tokens_fresh"] + span["input_tokens_cached"],
            "output_tokens": span["output_tokens"],
            "cost_usd": round(span["cost_usd"], 5),
            "cumulative_usd": round(cumulative, 4),
            "elapsed_s": round(wall_s, 1),
            "velocity_usd_per_min": round(velocity, 4),
            "velocity_multiplier": round(multiplier, 2),
            "identical_calls": identical,
            "tripped": tripped if trip is None else None,
        })

        if tripped and trip is None:
            trip = {
                "index": i,
                "breaker": tripped,
                "label": BREAKER_LABELS[tripped],
                "detail": detail,
                "spent_usd": round(cumulative, 4),
                "elapsed_s": round(wall_s, 1),
            }

    total_cost = total = sum(s["cost_usd"] for s in ordered)
    spent = trip["spent_usd"] if trip else round(total, 4)
    prevented = round(total - spent, 4)
    total_wall_s = (
        (datetime.fromisoformat(ordered[-1]["started_at"]) - start).total_seconds()
        + ordered[-1]["latency_ms"] / 1000.0
    )
    burn_rate = total / (total_wall_s / 60.0) if total_wall_s > 0 else 0.0

    would_have_caught = sorted(first_breach.values(), key=lambda b: b["index"])
    for entry in would_have_caught:
        entry["fired"] = bool(trip and entry["breaker"] == trip["breaker"])
        entry["prevented_usd"] = round(total_cost - entry["spent_usd"], 4)

    return {
        "breakers": breakers,
        "trailing_baseline_usd_per_min": round(baseline_usd_per_min, 4),
        "frames": frames,
        "trip": trip,
        "breaker_summary": [
            {
                "breaker": name,
                "label": BREAKER_LABELS[name],
                "limit": breakers[name],
                "breached": name in first_breach,
                **({k: v for k, v in first_breach[name].items()
                    if k not in ("breaker", "label")} if name in first_breach else {}),
            }
            for name in BREAKER_LABELS
        ],
        "counterfactual": {
            "spent_usd": spent,
            "prevented_usd": prevented,
            "total_if_unchecked_usd": round(total, 4),
            "spans_executed": (trip["index"] + 1) if trip else len(ordered),
            "spans_prevented": (len(ordered) - trip["index"] - 1) if trip else 0,
            "trace_duration_s": round(total_wall_s, 1),
            "burn_rate_usd_per_min": round(burn_rate, 2),
            "monthly_cap_usd": monthly_cap_usd,
            "minutes_to_burn_monthly_cap": (
                round(monthly_cap_usd / burn_rate, 1) if burn_rate > 0 else None
            ),
            "monthly_cap_comment": (
                f"At this trace's burn rate of ${burn_rate:.2f}/min, the entire "
                f"${monthly_cap_usd:.0f} monthly budget goes in "
                f"{monthly_cap_usd / burn_rate:.0f} minutes. A monthly cap is a level "
                "control; this needs a derivative control."
                if burn_rate > 0 else "Trace has no measurable duration."
            ),
        },
    }
