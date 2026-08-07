"""
Unit tests for the promotion engine — the one place tests are mandatory.

Three cases the spec names: pass, fail-on-floor, fail-on-significance. Plus the
cost-per-successful-outcome reversal, because that number is the pitch.

No FastAPI, no sqlite: these exercise the pure service functions directly.
"""

from __future__ import annotations

import pytest

from app.service.measurement import (
    PROMOTE,
    REJECT,
    MeasurementError,
    aggregate_quality,
    compute_baseline,
    cost_per_successful_outcome,
    evaluate_candidate,
    promotion_decision,
)

POLICY = {
    "quality_floor": {"clause_recall": 0.92, "truncation_rate": 0.0},
    "latency_ceiling_ms": 45000,
    "monthly_budget_usd": 400,
}

DOCS = [f"DOC-{i:03d}" for i in range(24)]


def _span(doc_id: str, cost: float, latency: int, stage: str = "clause_extract") -> dict:
    """A minimal recorded span. cost_usd is already metered by the CostMeter."""
    return {
        "span_id": f"{doc_id}-{stage}",
        "doc_id": doc_id,
        "stage": stage,
        "cost_usd": cost,
        "latency_ms": latency,
        "cost_bucket": "inference",
        "input_tokens_fresh": 1000,
        "input_tokens_cached": 0,
        "output_tokens": 100,
        "reasoning_tokens": 0,
    }


def _outcome(doc_id: str, recall: float, truncated: float, rework: float, succeeded: bool) -> dict:
    return {
        "outcome_id": f"OUT-{doc_id}",
        "doc_id": doc_id,
        "succeeded": succeeded,
        "human_rework_minutes": rework,
        "quality_scores": {"clause_recall": recall, "truncation_rate": truncated},
    }


def _pack(config_id: str, cost: float | list[float], latency: int, recall: float,
          truncated: float, rework: float, succeeded: bool) -> tuple[dict, list[dict]]:
    """`cost` is either a flat per-document cost or one cost per golden document."""
    costs = cost if isinstance(cost, list) else [cost] * len(DOCS)
    assert len(costs) == len(DOCS)
    spans, outcomes = [], []
    for doc, doc_cost in zip(DOCS, costs):
        spans.append(_span(doc, doc_cost, latency))
        outcomes.append(_outcome(doc, recall, truncated, rework, succeeded))
    return compute_baseline(spans, outcomes, config_id), outcomes


def _decide(base_pack, cand_pack):
    base, base_out = base_pack
    cand, cand_out = cand_pack
    comparison = evaluate_candidate(base, cand, base_out, cand_out)
    return promotion_decision(base, cand, POLICY, comparison), comparison


# --- pass ---------------------------------------------------------------------
def test_promotes_a_real_saving_that_holds_every_floor():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("optimised", cost=0.41, latency=28000, recall=0.94, truncated=0.0,
                 rework=7.5, succeeded=True)
    decision, comparison = _decide(base, cand)

    assert decision["decision"] == PROMOTE
    assert decision["reasons"] == []
    assert decision["failed_floors"] == []
    assert {f["metric"] for f in decision["passed_floors"]} == {"clause_recall", "truncation_rate"}
    assert comparison["cost"]["saving_is_significant"] is True
    assert decision["cost_delta_pct"] < 0
    assert "PROMOTED" in decision["headline"]


# --- fail on floor ------------------------------------------------------------
def test_rejects_a_large_saving_that_breaches_the_quality_floor():
    """The whole pitch: cheaper, measurably cheaper, and refused anyway."""
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("naive_cheap", cost=0.29, latency=16000, recall=0.61, truncated=0.54,
                 rework=37.0, succeeded=False)
    decision, comparison = _decide(base, cand)

    assert decision["decision"] == REJECT
    codes = {r["code"] for r in decision["reasons"]}
    assert codes == {"quality_floor_breach"}

    # The saving is real and significant — and irrelevant.
    assert comparison["cost"]["cheaper"] is True
    assert comparison["cost"]["saving_is_significant"] is True
    assert decision["cost_delta_pct"] < -50

    failed = {f["metric"]: f for f in decision["failed_floors"]}
    assert set(failed) == {"clause_recall", "truncation_rate"}
    assert failed["clause_recall"]["shortfall"] == pytest.approx(0.31, abs=1e-6)
    # truncation_rate is lower_is_better: the violation is measured the other way.
    assert failed["truncation_rate"]["shortfall"] == pytest.approx(0.54, abs=1e-6)
    assert "clause_recall 0.61 < floor 0.92" in decision["headline"]


def test_lower_is_better_metric_is_not_flagged_when_it_improves():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.2,
                 rework=7.0, succeeded=True)
    cand = _pack("cand", cost=0.50, latency=30000, recall=0.94, truncated=0.0,
                 rework=7.0, succeeded=True)
    decision, _ = _decide(base, cand)
    assert decision["decision"] == PROMOTE


# --- fail on significance -----------------------------------------------------
def test_rejects_a_saving_indistinguishable_from_noise():
    """
    A 2% mean saving swamped by per-document variance: half the documents got
    cheaper by 0.32, half got dearer by 0.30. The floors all hold and the total
    is genuinely lower — but on 24 paired documents that difference is noise, and
    promoting noise is how a control plane loses its credibility.
    """
    flat = [0.500] * len(DOCS)
    wobbly = [0.500 + (0.30 if i % 2 else -0.32) for i in range(len(DOCS))]
    base = _pack("baseline", cost=flat, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("marginal", cost=wobbly, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    decision, comparison = _decide(base, cand)

    assert decision["decision"] == REJECT
    assert {r["code"] for r in decision["reasons"]} == {"saving_not_significant"}
    assert decision["failed_floors"] == []
    assert comparison["cost"]["cheaper"] is True
    assert comparison["cost"]["saving_is_significant"] is False
    assert "includes 0" in decision["reasons"][0]["detail"]


def test_rejects_a_candidate_that_costs_more():
    base = _pack("baseline", cost=0.40, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("pricier", cost=0.55, latency=30000, recall=0.96, truncated=0.0,
                 rework=7.0, succeeded=True)
    decision, _ = _decide(base, cand)
    assert decision["decision"] == REJECT
    assert decision["reasons"][0]["code"] == "saving_not_significant"
    assert "not cheaper" in decision["reasons"][0]["detail"]


# --- latency ceiling ----------------------------------------------------------
def test_rejects_on_latency_ceiling_even_when_cheaper_and_accurate():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("batched", cost=0.35, latency=61000, recall=0.94, truncated=0.0,
                 rework=7.0, succeeded=True)
    decision, _ = _decide(base, cand)
    assert decision["decision"] == REJECT
    assert "latency_ceiling_breach" in {r["code"] for r in decision["reasons"]}
    assert decision["latency_breach"]["over_by_ms"] == 16000


def test_reports_every_failure_not_just_the_first():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("bad", cost=0.80, latency=70000, recall=0.55, truncated=0.9,
                 rework=40.0, succeeded=False)
    decision, _ = _decide(base, cand)
    assert {r["code"] for r in decision["reasons"]} == {
        "quality_floor_breach", "latency_ceiling_breach", "saving_not_significant",
    }


# --- cost per successful outcome ---------------------------------------------
def test_cheap_config_is_more_expensive_per_successful_outcome():
    """Success criterion 2: the reversal, once rework is in the numerator."""
    expensive = [_outcome(d, 0.95, 0.0, 7.0, True) for d in DOCS]
    cheap = [_outcome(d, 0.61, 0.54, 37.0, i < 8) for i, d in enumerate(DOCS)]

    exp = cost_per_successful_outcome(17.16, expensive, hourly_rate=95.0)
    chp = cost_per_successful_outcome(6.93, cheap, hourly_rate=95.0)

    assert exp["successes"] == 24
    assert chp["successes"] == 8
    # Cheaper per call...
    assert 6.93 < 17.16
    # ...and far more expensive per unit of work anyone can actually use.
    assert chp["value_usd"] > exp["value_usd"] * 5
    assert chp["rework_usd"] > chp["model_spend_usd"] * 10


def test_no_successful_outcomes_is_undefined_not_zero():
    none_worked = [_outcome(d, 0.4, 1.0, 60.0, False) for d in DOCS]
    result = cost_per_successful_outcome(5.0, none_worked)
    assert result["value_usd"] is None
    assert result["undefined_reason"] == "no_successful_outcomes"


# --- fail loudly --------------------------------------------------------------
def test_refuses_to_promote_against_an_unmeasured_floor():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand_pack, cand_outcomes = _pack("partial", cost=0.4, latency=30000, recall=0.94,
                                     truncated=0.0, rework=7.0, succeeded=True)
    del cand_pack["quality"]["clause_recall"]
    comparison = evaluate_candidate(base[0], cand_pack, base[1], cand_outcomes)
    with pytest.raises(MeasurementError, match="no measurement of it"):
        promotion_decision(base[0], cand_pack, POLICY, comparison)


def test_refuses_to_compare_unpaired_run_sets():
    base, base_out = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                           rework=7.0, succeeded=True)
    other_spans = [_span("OTHER-1", 0.4, 30000)]
    other_outcomes = [_outcome("OTHER-1", 0.94, 0.0, 7.0, True)]
    cand = compute_baseline(other_spans, other_outcomes, "unpaired")
    with pytest.raises(MeasurementError, match="share no documents"):
        evaluate_candidate(base, cand, base_out, other_outcomes)


def test_refuses_to_aggregate_zero_outcomes():
    with pytest.raises(MeasurementError):
        aggregate_quality([])


def test_policy_without_a_floor_is_an_error():
    base = _pack("baseline", cost=0.72, latency=30000, recall=0.95, truncated=0.0,
                 rework=7.0, succeeded=True)
    cand = _pack("cand", cost=0.4, latency=30000, recall=0.94, truncated=0.0,
                 rework=7.0, succeeded=True)
    comparison = evaluate_candidate(base[0], cand[0], base[1], cand[1])
    with pytest.raises(MeasurementError, match="no quality_floor"):
        promotion_decision(base[0], cand[0], {"latency_ceiling_ms": 45000}, comparison)
