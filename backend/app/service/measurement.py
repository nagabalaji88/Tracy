"""
MODULE 1 — the measurement core and the promotion engine.

This is the part nobody else has built: a decision procedure that will refuse a
cost saving. Everything here is a pure function over plain dicts. No FastAPI
import, no sqlite import — it is unit-testable in isolation, and it is.

The constrained optimisation it implements:

    minimize cost   subject to   quality >= floor   AND   latency <= ceiling

A candidate that is cheaper and fails a floor is not a win with a caveat. It is
a rejection.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from app.policy import (
    floor_violation,
    metric_direction,
    metric_label,
    rework_hourly_rate,
    significance_settings,
)
from app.service.stats import mean, paired_bootstrap, percentile, sign_test

PROMOTE = "PROMOTE"
REJECT = "REJECT"


class MeasurementError(RuntimeError):
    """Raised when a number would have to be invented to answer the question."""


# --- aggregation --------------------------------------------------------------
def aggregate_quality(outcomes: Sequence[dict]) -> dict[str, float]:
    """
    Mean of each recorded metric across the run set.

    A per-run truncation flag of 0/1 aggregates to exactly the truncation *rate*
    the floor is written against. Metrics missing from a run are skipped, never
    imputed — so a metric that was measured on half the set reports the mean of
    that half and its own n.
    """
    if not outcomes:
        raise MeasurementError("cannot aggregate quality over zero recorded outcomes")
    buckets: dict[str, list[float]] = defaultdict(list)
    for outcome in outcomes:
        scores = outcome.get("quality_scores")
        if scores is None:
            raise MeasurementError(f"outcome {outcome.get('outcome_id')} has no quality_scores")
        for metric, value in scores.items():
            buckets[metric].append(float(value))
    return {metric: round(mean(values), 6) for metric, values in sorted(buckets.items())}


def quality_sample_sizes(outcomes: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        for metric in outcome["quality_scores"]:
            counts[metric] += 1
    return dict(counts)


def per_document_cost(spans: Sequence[dict]) -> dict[str, float]:
    costs: dict[str, float] = defaultdict(float)
    for span in spans:
        if span.get("doc_id") is None:
            raise MeasurementError(f"span {span.get('span_id')} has no doc_id to attribute to")
        costs[span["doc_id"]] += span["cost_usd"]
    return dict(costs)


def per_document_latency(spans: Sequence[dict]) -> dict[str, int]:
    """Wall-clock of the pipeline per document: the stages run sequentially."""
    lat: dict[str, int] = defaultdict(int)
    for span in spans:
        lat[span["doc_id"]] += span["latency_ms"]
    return dict(lat)


def cost_per_successful_outcome(
    model_spend_usd: float,
    outcomes: Sequence[dict],
    hourly_rate: float | None = None,
) -> dict[str, Any]:
    """
    The metric the FinOps Foundation says matters, and that no shipping product
    computes: total cost of getting work that was actually usable.

        (model spend + human rework cost) / successful outcomes

    Rework minutes are in the numerator because an analyst repairing a cheap
    model's output is a cost of that model, charged to a different budget line.
    """
    if not outcomes:
        raise MeasurementError("cost per successful outcome over zero outcomes is undefined")
    rate = rework_hourly_rate() if hourly_rate is None else hourly_rate
    rework_minutes = sum(float(o["human_rework_minutes"]) for o in outcomes)
    rework_usd = rework_minutes / 60.0 * rate
    successes = sum(1 for o in outcomes if o["succeeded"])
    numerator = model_spend_usd + rework_usd
    return {
        "model_spend_usd": round(model_spend_usd, 4),
        "rework_minutes": round(rework_minutes, 2),
        "rework_usd": round(rework_usd, 4),
        "hourly_rate_usd": rate,
        "numerator_usd": round(numerator, 4),
        "successes": successes,
        "attempts": len(outcomes),
        "success_rate": round(successes / len(outcomes), 4),
        # Undefined, not zero, not infinity. A configuration that never produced a
        # usable result has no cost per successful outcome — and saying so is more
        # honest than printing a very large number.
        "value_usd": round(numerator / successes, 4) if successes else None,
        "undefined_reason": None if successes else "no_successful_outcomes",
    }


def compute_baseline(
    spans: Sequence[dict],
    outcomes: Sequence[dict],
    config_id: str,
    label: str | None = None,
) -> dict[str, Any]:
    """
    Everything measured about one configuration over one run set.

    Named compute_baseline because that is its role in the comparison, but it is
    the same computation for a candidate — there is no privileged configuration.
    """
    if not spans:
        raise MeasurementError(f"config '{config_id}' has no recorded spans")
    if not outcomes:
        raise MeasurementError(f"config '{config_id}' has no recorded outcomes")

    doc_cost = per_document_cost(spans)
    doc_latency = per_document_latency(spans)
    total_spend = sum(doc_cost.values())
    costs = list(doc_cost.values())
    latencies = [float(v) for v in doc_latency.values()]

    stage_cost: dict[str, float] = defaultdict(float)
    bucket_cost: dict[str, float] = defaultdict(float)
    tokens = {"input_fresh": 0, "input_cached": 0, "output": 0, "reasoning": 0}
    for span in spans:
        stage_cost[span["stage"]] += span["cost_usd"]
        bucket_cost[span["cost_bucket"]] += span["cost_usd"]
        tokens["input_fresh"] += span["input_tokens_fresh"]
        tokens["input_cached"] += span["input_tokens_cached"]
        tokens["output"] += span["output_tokens"]
        tokens["reasoning"] += span["reasoning_tokens"]

    return {
        "config_id": config_id,
        "label": label or config_id,
        "n_documents": len(doc_cost),
        "n_spans": len(spans),
        "total_spend_usd": round(total_spend, 4),
        "cost_per_document_usd": round(total_spend / len(doc_cost), 6),
        "cost_percentiles_usd": {
            "p50": round(percentile(costs, 50), 6),
            "p95": round(percentile(costs, 95), 6),
            "p99": round(percentile(costs, 99), 6),
        },
        "latency_ms": {
            "p50": round(percentile(latencies, 50)),
            "p95": round(percentile(latencies, 95)),
            "p99": round(percentile(latencies, 99)),
        },
        "quality": aggregate_quality(outcomes),
        "quality_n": quality_sample_sizes(outcomes),
        "cost_per_successful_outcome": cost_per_successful_outcome(total_spend, outcomes),
        "spend_by_stage_usd": {k: round(v, 6) for k, v in sorted(stage_cost.items())},
        "spend_by_bucket_usd": {k: round(v, 6) for k, v in sorted(bucket_cost.items())},
        "tokens": tokens,
        "per_document": {
            doc_id: {
                "cost_usd": round(doc_cost[doc_id], 6),
                "latency_ms": doc_latency.get(doc_id, 0),
            }
            for doc_id in sorted(doc_cost)
        },
    }


# --- paired comparison --------------------------------------------------------
def _pair(baseline_outcomes: Sequence[dict], candidate_outcomes: Sequence[dict]) -> list[str]:
    """Documents present in both run sets. Comparing anything else is not paired."""
    b = {o["doc_id"] for o in baseline_outcomes}
    c = {o["doc_id"] for o in candidate_outcomes}
    shared = sorted(b & c)
    if not shared:
        raise MeasurementError(
            "baseline and candidate share no documents; a paired comparison is "
            "impossible. Re-run the candidate over the same golden set."
        )
    return shared


def evaluate_candidate(
    baseline: dict,
    candidate: dict,
    baseline_outcomes: Sequence[dict],
    candidate_outcomes: Sequence[dict],
) -> dict[str, Any]:
    """
    Paired comparison of a candidate against a baseline over the same documents.

    Per-metric delta plus a significance check on each. The significance check is
    not optional decoration: a 4% "saving" measured on 24 documents can easily be
    noise, and promoting noise is how a control plane loses its credibility.
    """
    settings = significance_settings()
    shared = _pair(baseline_outcomes, candidate_outcomes)
    b_by_doc = {o["doc_id"]: o for o in baseline_outcomes}
    c_by_doc = {o["doc_id"]: o for o in candidate_outcomes}

    # --- cost, paired per document
    cost_deltas = [
        candidate["per_document"][d]["cost_usd"] - baseline["per_document"][d]["cost_usd"]
        for d in shared
        if d in baseline["per_document"] and d in candidate["per_document"]
    ]
    cost_stats = paired_bootstrap(
        cost_deltas,
        iterations=settings["bootstrap_iterations"],
        confidence=settings["confidence"],
        seed=settings["seed"],
    )
    cost_sign = sign_test(cost_deltas)

    # --- quality, paired per document, per metric
    metric_names = sorted(set(baseline["quality"]) & set(candidate["quality"]))
    quality: dict[str, Any] = {}
    for metric in metric_names:
        deltas = [
            c_by_doc[d]["quality_scores"][metric] - b_by_doc[d]["quality_scores"][metric]
            for d in shared
            if metric in b_by_doc[d]["quality_scores"] and metric in c_by_doc[d]["quality_scores"]
        ]
        if not deltas:
            continue
        stats = paired_bootstrap(
            deltas,
            iterations=settings["bootstrap_iterations"],
            confidence=settings["confidence"],
            seed=settings["seed"],
        )
        direction = metric_direction(metric)
        observed = stats["observed_mean_delta"]
        improved = observed > 0 if direction == "higher_is_better" else observed < 0
        quality[metric] = {
            "label": metric_label(metric),
            "direction": direction,
            "baseline": baseline["quality"][metric],
            "candidate": candidate["quality"][metric],
            "delta": round(observed, 6),
            "improved": bool(improved),
            "bootstrap": stats,
            "sign_test": sign_test(deltas),
        }

    baseline_total = baseline["total_spend_usd"]
    candidate_total = candidate["total_spend_usd"]
    b_cpso = baseline["cost_per_successful_outcome"]["value_usd"]
    c_cpso = candidate["cost_per_successful_outcome"]["value_usd"]

    return {
        "baseline_config_id": baseline["config_id"],
        "candidate_config_id": candidate["config_id"],
        "n_paired_documents": len(shared),
        "cost": {
            "baseline_total_usd": baseline_total,
            "candidate_total_usd": candidate_total,
            "delta_usd": round(candidate_total - baseline_total, 6),
            "pct_change": round((candidate_total - baseline_total) / baseline_total * 100, 3),
            "baseline_per_document_usd": baseline["cost_per_document_usd"],
            "candidate_per_document_usd": candidate["cost_per_document_usd"],
            "bootstrap": cost_stats,
            "sign_test": cost_sign,
            "cheaper": candidate_total < baseline_total,
            "saving_is_significant": bool(cost_stats["ci_high"] < 0),
        },
        "latency": {
            "baseline_p95_ms": baseline["latency_ms"]["p95"],
            "candidate_p95_ms": candidate["latency_ms"]["p95"],
            "delta_ms": candidate["latency_ms"]["p95"] - baseline["latency_ms"]["p95"],
        },
        "quality": quality,
        "cost_per_successful_outcome": {
            "baseline_usd": b_cpso,
            "candidate_usd": c_cpso,
            # The reversal, when it happens, happens here.
            "pct_change": (
                round((c_cpso - b_cpso) / b_cpso * 100, 2)
                if (b_cpso and c_cpso) else None
            ),
            "candidate_undefined_reason":
                candidate["cost_per_successful_outcome"]["undefined_reason"],
        },
    }


def promotion_decision(
    baseline: dict,
    candidate: dict,
    policy: dict,
    comparison: dict | None = None,
    baseline_outcomes: Sequence[dict] | None = None,
    candidate_outcomes: Sequence[dict] | None = None,
) -> dict[str, Any]:
    """
    PROMOTE or REJECT, with the specific floor that failed and by how much.

    `policy` is the use-case entry from policy.yaml. `comparison` is the output of
    evaluate_candidate; if omitted it is computed, which requires the outcome
    lists.

    Rejection reasons, all evaluated (a candidate that fails three ways is told
    about three, not one):
      quality_floor_breach      a declared floor was crossed
      latency_ceiling_breach    p95 exceeded the declared ceiling
      saving_not_significant    the saving is not distinguishable from noise
    """
    if comparison is None:
        if baseline_outcomes is None or candidate_outcomes is None:
            raise MeasurementError(
                "promotion_decision needs either a precomputed comparison or both "
                "outcome lists; it will not decide on partial evidence"
            )
        comparison = evaluate_candidate(baseline, candidate, baseline_outcomes, candidate_outcomes)

    if "quality_floor" not in policy:
        raise MeasurementError(
            "the use-case policy declares no quality_floor. A control plane with no "
            "floor cannot reject anything, which is the one thing it exists to do."
        )

    failed_floors: list[dict[str, Any]] = []
    passed_floors: list[dict[str, Any]] = []
    for metric, floor in policy["quality_floor"].items():
        if metric not in candidate["quality"]:
            raise MeasurementError(
                f"policy declares a floor on '{metric}' but the candidate run set has "
                f"no measurement of it. Refusing to promote against an unmeasured floor."
            )
        value = candidate["quality"][metric]
        shortfall = floor_violation(metric, value, floor)
        record = {
            "metric": metric,
            "label": metric_label(metric),
            "direction": metric_direction(metric),
            "floor": floor,
            "candidate_value": value,
            "baseline_value": baseline["quality"].get(metric),
            "shortfall": shortfall,
            "n": candidate["quality_n"].get(metric),
        }
        (failed_floors if shortfall is not None else passed_floors).append(record)

    reasons: list[dict[str, Any]] = []
    if failed_floors:
        # The reported breach is the FIRST failing floor in policy declaration
        # order, not the numerically largest shortfall. Shortfalls on different
        # metrics are in different units — 0.31 of recall is not comparable to
        # 0.54 of truncation rate — so ranking them would be meaningless. Policy
        # order is the business's own statement of what it cares about first.
        primary = failed_floors[0]
        reasons.append({
            "code": "quality_floor_breach",
            "metric": primary["metric"],
            "detail": (
                f"{primary['label']} {primary['candidate_value']:.4g} "
                f"{'<' if primary['direction'] == 'higher_is_better' else '>'} "
                f"floor {primary['floor']:.4g}"
            ),
            "magnitude": primary["shortfall"],
        })

    ceiling = policy.get("latency_ceiling_ms")
    latency_breach = None
    if ceiling is not None:
        p95 = candidate["latency_ms"]["p95"]
        if p95 > ceiling:
            latency_breach = {"p95_ms": p95, "ceiling_ms": ceiling, "over_by_ms": p95 - ceiling}
            reasons.append({
                "code": "latency_ceiling_breach",
                "metric": "latency_p95_ms",
                "detail": f"p95 latency {p95} ms > ceiling {ceiling} ms",
                "magnitude": p95 - ceiling,
            })

    cost = comparison["cost"]
    if not cost["cheaper"]:
        reasons.append({
            "code": "saving_not_significant",
            "metric": "cost",
            "detail": f"candidate is not cheaper ({cost['pct_change']:+.2f}% spend)",
            "magnitude": cost["delta_usd"],
        })
    elif not cost["saving_is_significant"]:
        reasons.append({
            "code": "saving_not_significant",
            "metric": "cost",
            "detail": (
                f"saving of {abs(cost['pct_change']):.2f}% is not distinguishable from "
                f"noise on {comparison['n_paired_documents']} paired documents "
                f"(bootstrap CI {cost['bootstrap']['ci_low']:+.4f} to "
                f"{cost['bootstrap']['ci_high']:+.4f} USD/doc includes 0)"
            ),
            "magnitude": cost["bootstrap"]["ci_high"],
        })

    # Not a rejection, but the reviewer should see it: a metric that regressed
    # significantly while staying above its floor is floor erosion in progress.
    warnings: list[dict[str, Any]] = []
    for metric, q in comparison["quality"].items():
        if not q["improved"] and q["bootstrap"]["significant"]:
            warnings.append({
                "code": "significant_quality_regression_above_floor",
                "metric": metric,
                "detail": (
                    f"{q['label']} moved {q['delta']:+.4f} "
                    f"(sign test p={q['sign_test']['p_value']}), still inside the floor"
                ),
            })

    decision = REJECT if reasons else PROMOTE
    return {
        "decision": decision,
        "baseline_config_id": baseline["config_id"],
        "candidate_config_id": candidate["config_id"],
        "reasons": reasons,
        "warnings": warnings,
        "failed_floors": failed_floors,
        "passed_floors": passed_floors,
        "latency_breach": latency_breach,
        "cost_delta_pct": cost["pct_change"],
        "cost_saving_usd": round(-cost["delta_usd"], 6),
        "n_paired_documents": comparison["n_paired_documents"],
        "headline": _headline(decision, comparison, failed_floors),
    }


def _headline(decision: str, comparison: dict, failed_floors: list[dict]) -> str:
    pct = comparison["cost"]["pct_change"]
    if decision == PROMOTE:
        return f"PROMOTED — {abs(pct):.0f}% cheaper, every declared floor held"
    if failed_floors:
        primary = failed_floors[0]
        sign = "<" if primary["direction"] == "higher_is_better" else ">"
        return (
            f"REJECTED — {primary['metric']} {primary['candidate_value']:.4g} {sign} "
            f"floor {primary['floor']:.4g} (cost {pct:+.0f}%)"
        )
    return f"REJECTED — {comparison['cost']['pct_change']:+.0f}% cost change, no promotable saving"
