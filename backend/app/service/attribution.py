"""
MODULE 2 — attribution and cost explorer.

Rollups are the easy part. The parts that matter:

  * the cost buckets most tools never separate — retries, cache reads, CI/eval
    spend, embedding regeneration, and human rework;
  * stage economics: what each agent stage costs and what quality it actually
    buys, measured by ablation rather than asserted;
  * the heavy tail, because the mean cost per document is a number nobody's
    invoice ever matches.

Pure functions over lists of span dicts and outcome dicts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from app.policy import metric_direction, metric_label, rework_hourly_rate
from app.service.measurement import MeasurementError
from app.service.stats import percentile

# Buckets and what they mean. The `note` is shown in the UI: a cost line nobody
# can explain is a cost line nobody acts on.
BUCKET_NOTES = {
    "inference": "First-attempt model calls. The only line most dashboards show.",
    "retry": "Re-runs after a structured-output failure. Invisible in per-call pricing.",
    "eval": "CI and evaluation spend. Charged to engineering, caused by the product.",
    "embedding": "Index build and regeneration, including re-indexing on prompt change.",
    "tool": "Tool-call round trips inside an agent loop.",
    "rework": "Human time repairing model output, at the configured hourly rate.",
}


def _sum_by(spans: Sequence[dict], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for span in spans:
        out[str(span[key])] += span["cost_usd"]
    return dict(out)


def _count_by(spans: Sequence[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for span in spans:
        out[str(span[key])] += 1
    return dict(out)


def _rollup(spans: Sequence[dict], key: str, total: float) -> list[dict[str, Any]]:
    spend = _sum_by(spans, key)
    counts = _count_by(spans, key)
    docs: dict[str, set] = defaultdict(set)
    for span in spans:
        if span.get("doc_id"):
            docs[str(span[key])].add(span["doc_id"])
    rows = []
    for k in sorted(spend, key=lambda k: -spend[k]):
        n_docs = len(docs.get(k, ()))
        rows.append({
            "key": k,
            "spend_usd": round(spend[k], 4),
            "spans": counts[k],
            "share_pct": round(spend[k] / total * 100, 2) if total else 0.0,
            "documents": n_docs,
            "cost_per_document_usd": round(spend[k] / n_docs, 6) if n_docs else None,
        })
    return rows


def rollup(spans: Sequence[dict], outcomes: Sequence[dict]) -> dict[str, Any]:
    """Spend by every dimension the trace carries, plus the buckets and the cache."""
    if not spans:
        raise MeasurementError("no spans in the requested window; nothing to attribute")
    total = sum(s["cost_usd"] for s in spans)

    # Rework is real money and belongs beside the model spend, but it is not a
    # span — it comes from the outcome table. It is reported as a derived line,
    # explicitly labelled, never mixed into the span totals.
    rework_minutes = sum(float(o["human_rework_minutes"]) for o in outcomes)
    rework_usd = rework_minutes / 60.0 * rework_hourly_rate()

    bucket_spend = _sum_by(spans, "cost_bucket")
    grand_total = total + rework_usd
    buckets = [
        {
            "key": key,
            "label": key.replace("_", " ").title(),
            "spend_usd": round(value, 4),
            "share_pct": round(value / grand_total * 100, 2),
            "note": BUCKET_NOTES.get(key, ""),
            "measured": True,
        }
        for key, value in sorted(bucket_spend.items(), key=lambda kv: -kv[1])
    ]
    buckets.append({
        "key": "rework",
        "label": "Human Rework",
        "spend_usd": round(rework_usd, 4),
        "share_pct": round(rework_usd / grand_total * 100, 2),
        "note": (
            f"{round(rework_minutes / 60, 1)} analyst hours at "
            f"${rework_hourly_rate():.0f}/hr, from the outcome table. Not a span — "
            "a derived line, shown because it is the largest cost in the system."
        ),
        "measured": True,
    })

    fresh_tokens = sum(s["input_tokens_fresh"] for s in spans)
    cached_tokens = sum(s["input_tokens_cached"] for s in spans)
    # What the cached reads would have cost at the fresh rate. Derived from the
    # same pricing table the CostMeter uses, per model, so it is not a guess.
    from app.policy import model_pricing

    cached_usd = 0.0
    counterfactual = 0.0
    fresh_usd = 0.0
    for span in spans:
        rates = model_pricing(span["model"])
        cached_usd += span["input_tokens_cached"] * rates["cached_input"] / 1e6
        counterfactual += span["input_tokens_cached"] * rates["fresh_input"] / 1e6
        fresh_usd += span["input_tokens_fresh"] * rates["fresh_input"] / 1e6

    dates = sorted(s["started_at"] for s in spans)
    return {
        "window": {
            "from": dates[0],
            "to": dates[-1],
            "days": len({d[:10] for d in dates}),
        },
        # Two totals, deliberately. Model spend is what the invoice says; the
        # grand total is what the work cost. They differ by an order of magnitude
        # and only one of them is on anyone's dashboard.
        "total_spend_usd": round(total, 4),
        "model_spend_usd": round(total, 4),
        "rework_usd": round(rework_usd, 4),
        "rework_hours": round(rework_minutes / 60, 2),
        "grand_total_usd": round(grand_total, 4),
        "rework_multiple_of_model_spend": round(rework_usd / total, 2) if total else None,
        "by_team": _rollup(spans, "team", total),
        "by_use_case": _rollup(spans, "use_case", total),
        "by_stage": _rollup(spans, "stage", total),
        "by_prompt_version": _rollup(spans, "prompt_version", total),
        "by_model": _rollup(spans, "model", total),
        "buckets": buckets,
        "cached_vs_fresh": {
            "fresh_tokens": fresh_tokens,
            "cached_tokens": cached_tokens,
            "fresh_usd": round(fresh_usd, 4),
            "cached_usd": round(cached_usd, 4),
            "cache_hit_rate": round(
                cached_tokens / (fresh_tokens + cached_tokens), 4
            ) if (fresh_tokens + cached_tokens) else 0.0,
            "counterfactual_usd_without_cache": round(counterfactual, 4),
            "saved_usd": round(counterfactual - cached_usd, 4),
        },
    }


def stage_economics(
    baseline_spans: Sequence[dict],
    baseline_outcomes: Sequence[dict],
    ablations: dict[str, tuple[Sequence[dict], Sequence[dict]]],
    primary_metric: str,
    non_ablatable: Sequence[str] = (),
) -> dict[str, Any]:
    """
    Is Agent 3 worth what it costs?

    For each stage: what it costs, and what removing it does — to quality, and to
    the only number that settles the argument, cost per successful outcome. A
    stage that saves model spend and costs more per usable result is not a saving.

    Answered from recorded ablation runs over the same golden set. A stage with no
    ablation run gets `ablation_available: false` and no verdict, because the
    honest answer is "not measured".
    """
    from app.service.measurement import aggregate_quality, cost_per_successful_outcome

    if not baseline_spans:
        raise MeasurementError("no baseline spans; stage economics is undefined")
    total = sum(s["cost_usd"] for s in baseline_spans)
    n_docs = len({s["doc_id"] for s in baseline_spans if s.get("doc_id")})
    base_quality = aggregate_quality(baseline_outcomes)
    base_cpso = cost_per_successful_outcome(total, baseline_outcomes)
    direction = metric_direction(primary_metric)

    stage_spend = _sum_by(baseline_spans, "stage")
    rows: list[dict[str, Any]] = []
    for stage in sorted(stage_spend, key=lambda s: -stage_spend[s]):
        spend = stage_spend[stage]
        row: dict[str, Any] = {
            "stage": stage,
            "spend_usd": round(spend, 4),
            "share_pct": round(spend / total * 100, 2),
            "cost_per_document_usd": round(spend / n_docs, 6) if n_docs else None,
            "ablation_config_id": None,
            "ablation_available": False,
            "quality_delta": None,
            "marginal_quality_per_usd": None,
            "verdict": "not_measured",
            "note": (
                f"{stage} is the pipeline — with it removed there is nothing left to "
                "measure, so no ablation exists."
                if stage in non_ablatable
                else "No ablation run recorded for this stage. Record one before "
                     "arguing about whether it earns its cost."
            ),
        }
        if stage in ablations:
            ab_spans, ab_outcomes = ablations[stage]
            ab_quality = aggregate_quality(ab_outcomes)
            ab_spend = sum(s["cost_usd"] for s in ab_spans)
            ab_cpso = cost_per_successful_outcome(ab_spend, ab_outcomes)
            # Positive delta = the stage improves the metric.
            delta = {
                m: round(base_quality[m] - ab_quality[m], 6)
                for m in base_quality
                if m in ab_quality
            }
            gain = delta.get(primary_metric, 0.0)
            if direction == "lower_is_better":
                gain = -gain
            model_saving = total - ab_spend  # what removing the stage saves on the invoice

            base_value = base_cpso["value_usd"]
            ab_value = ab_cpso["value_usd"]
            cpso_delta = (
                round(ab_value - base_value, 4)
                if (base_value is not None and ab_value is not None) else None
            )

            # Which metric does this stage actually buy? Report the largest
            # improvement across every recorded metric, not just the floor one.
            bought = max(
                ((m, d) for m, d in delta.items()),
                key=lambda kv: abs(kv[1]),
                default=(primary_metric, 0.0),
            )

            row.update(
                ablation_config_id=ab_spans[0]["config_id"],
                ablation_available=True,
                quality_delta=delta,
                model_saving_if_removed_usd=round(model_saving, 4),
                rework_delta_minutes=round(
                    ab_cpso["rework_minutes"] - base_cpso["rework_minutes"], 1),
                cpso_baseline_usd=base_value,
                cpso_without_stage_usd=ab_value,
                cpso_delta_usd=cpso_delta,
                marginal_quality_per_usd=(
                    round(gain / model_saving, 6) if model_saving > 0 else None
                ),
                buys_metric=bought[0],
                buys_amount=round(bought[1], 6),
            )

            if cpso_delta is None:
                row["verdict"] = "worth_it"
                row["note"] = (
                    f"Removing {stage} leaves no successful outcomes at all — cost per "
                    "successful outcome becomes undefined. The stage is load-bearing."
                )
            elif cpso_delta > 0:
                row["verdict"] = "worth_it"
                row["note"] = (
                    f"Removing {stage} saves ${model_saving:.2f} of model spend and raises "
                    f"cost per successful outcome by ${cpso_delta:.2f} "
                    f"(rework {row['rework_delta_minutes']:+.0f} min). It pays for itself."
                )
            else:
                row["verdict"] = "not_worth_it"
                spend_clause = (
                    f"saving ${model_saving:.2f} of model spend"
                    if model_saving > 0
                    else f"adding ${abs(model_saving):.2f} of model spend"
                )
                row["note"] = (
                    f"Removing {stage} lowers cost per successful outcome by "
                    f"${abs(cpso_delta):.2f} while {spend_clause} and moving "
                    f"{metric_label(bought[0]).lower()} by {bought[1]:+.4f}. "
                    "On this golden set the stage is not paying for itself."
                )
        rows.append(row)

    return {
        "baseline_config_id": baseline_spans[0]["config_id"],
        "primary_metric": primary_metric,
        "baseline_cost_per_successful_outcome_usd": base_cpso["value_usd"],
        "stages": rows,
    }


def heavy_tail(spans: Sequence[dict], outcomes: Sequence[dict]) -> dict[str, Any]:
    """
    p50/p95/p99 cost per document, and the share of spend the worst 5% consumes.

    Averages hide this completely, and it is where the budget actually goes.
    """
    if not spans:
        raise MeasurementError("no spans; the cost distribution is undefined")
    # Grouped by TRACE, not by doc_id: one trace is one unit of work. A workload
    # that analyses the same subject repeatedly has many work items per doc_id,
    # and collapsing them would hide the distribution this whole view is about.
    per_doc: dict[str, float] = defaultdict(float)
    trace_subject: dict[str, str] = {}
    for span in spans:
        per_doc[span["trace_id"]] += span["cost_usd"]
        trace_subject.setdefault(span["trace_id"], span.get("doc_id") or span["trace_id"])
    if not per_doc:
        raise MeasurementError("no spans carry a trace_id; cannot build a distribution")

    costs = sorted(per_doc.values(), reverse=True)
    total = sum(costs)
    n = len(costs)
    top5 = costs[: max(1, round(n * 0.05))]
    top1 = costs[: max(1, round(n * 0.01))]

    p50 = percentile(costs, 50)
    p99 = percentile(costs, 99)

    meta = {o["doc_id"]: o for o in outcomes}
    worst = [
        {
            "doc_id": trace_subject.get(trace_id, trace_id),
            "trace_id": trace_id,
            "cost_usd": round(cost, 4),
            "doc_tier": meta.get(trace_subject.get(trace_id, ""), {}).get("doc_tier"),
            "succeeded": meta.get(trace_subject.get(trace_id, ""), {}).get("succeeded"),
        }
        for trace_id, cost in sorted(per_doc.items(), key=lambda kv: -kv[1])[:10]
    ]

    # Linear bins over the full range are useless when the range spans three
    # orders of magnitude — which is exactly the situation worth showing. Bin the
    # body of the distribution up to p99 and put everything above it in one
    # explicit overflow bucket, so the tail is visible rather than flattened.
    lo, hi = min(costs), max(costs)
    n_buckets = 22
    body_hi = max(p99, lo + 1e-6)
    width = (body_hi - lo) / n_buckets
    histogram = []
    for i in range(n_buckets):
        b_lo, b_hi = lo + i * width, lo + (i + 1) * width
        count = sum(1 for c in costs if b_lo <= c < b_hi)
        histogram.append({
            "bucket_usd_lo": round(b_lo, 4),
            "bucket_usd_hi": round(b_hi, 4),
            "documents": count,
            "overflow": False,
        })
    overflow = [c for c in costs if c >= body_hi]
    histogram.append({
        "bucket_usd_lo": round(body_hi, 4),
        "bucket_usd_hi": round(hi, 4),
        "documents": len(overflow),
        "overflow": True,
    })

    tier_costs: dict[str, list[float]] = defaultdict(list)
    for trace_id, cost in per_doc.items():
        tier = meta.get(trace_subject.get(trace_id, ""), {}).get("doc_tier")
        if tier:
            tier_costs[tier].append(cost)
    by_tier = [
        {
            "tier": tier,
            "documents": len(values),
            "mean_usd": round(sum(values) / len(values), 5),
            "p95_usd": round(percentile(values, 95), 5),
            "share_pct": round(sum(values) / total * 100, 2),
        }
        for tier, values in sorted(tier_costs.items(), key=lambda kv: -sum(kv[1]))
    ]

    return {
        "n_documents": n,
        "percentiles_usd": {
            "p50": round(p50, 5),
            "p75": round(percentile(costs, 75), 5),
            "p90": round(percentile(costs, 90), 5),
            "p95": round(percentile(costs, 95), 5),
            "p99": round(p99, 5),
            "max": round(hi, 5),
            "mean": round(total / n, 5),
        },
        "top_5pct_share_of_spend": round(sum(top5) / total * 100, 2),
        "top_1pct_share_of_spend": round(sum(top1) / total * 100, 2),
        "ratio_p99_p50": round(p99 / p50, 2) if p50 else None,
        "histogram": histogram,
        "worst": worst,
        "by_tier": by_tier,
    }
