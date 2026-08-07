"""
Adapters for the `contract_analysis` workload.

The Scorer computes metrics from recorded run artifacts (which clause ids the
gold set contains, which the pipeline returned, which stage finish_reasons came
back truncated). It never fabricates a score: if an artifact is missing, it
raises.
"""

from __future__ import annotations

from typing import Any

from app.adapters.base import register_cost_meter, register_scorer
from app.adapters.token_cost_meter import TOKEN_COST_METER


class ContractAnalysisScorer:
    name = "contract_analysis_scorer/v1"
    metrics = ("clause_recall", "citation_accuracy", "truncation_rate", "hallucinated_clauses")
    REVIEW_THRESHOLD = 0.70

    def score(self, run: dict[str, Any]) -> dict[str, Any]:
        art = run.get("artifacts")
        if not art:
            raise ValueError(
                f"run {run.get('doc_id')!r} has no recorded artifacts; refusing to score it"
            )
        for key in ("gold_clause_ids", "predicted_clause_ids", "stage_finish_reasons",
                    "citations_checked", "citations_correct", "human_rework_minutes"):
            if key not in art:
                raise ValueError(f"run {run.get('doc_id')!r} artifact missing '{key}'")

        gold = set(art["gold_clause_ids"])
        pred = set(art["predicted_clause_ids"])
        if not gold:
            raise ValueError(f"run {run.get('doc_id')!r} has an empty gold clause set")

        recall = len(gold & pred) / len(gold)
        hallucinated = len(pred - gold)
        truncated = any(r == "length" for r in art["stage_finish_reasons"])
        checked = art["citations_checked"]
        if checked == 0:
            raise ValueError(f"run {run.get('doc_id')!r} recorded zero citation checks")
        citation_accuracy = art["citations_correct"] / checked

        scores = {
            "clause_recall": round(recall, 4),
            "citation_accuracy": round(citation_accuracy, 4),
            # Per-run truncation is 0 or 1; aggregated across a golden set it is
            # the rate the floor is written against.
            "truncation_rate": 1.0 if truncated else 0.0,
            "hallucinated_clauses": float(hallucinated),
        }

        # Business success is not "the call returned 200". A run succeeds when the
        # analyst could ship it: no truncation, recall at or above the review
        # threshold, and no invented clauses.
        #
        # REVIEW_THRESHOLD is the recall below which the reviewing analyst redoes
        # the analysis from scratch instead of correcting it. It is deliberately
        # lower than the policy floor: the floor is what the business will accept
        # in aggregate, this is what makes an individual document unusable.
        failure_reason = None
        if truncated:
            failure_reason = "output_truncated"
        elif recall < self.REVIEW_THRESHOLD:
            failure_reason = "clause_recall_below_review_threshold"
        elif hallucinated > 2:
            failure_reason = "hallucinated_clauses"

        return {
            "quality_scores": scores,
            "succeeded": failure_reason is None,
            "failure_reason": failure_reason,
            "human_rework_minutes": float(art["human_rework_minutes"]),
        }


class SupportTriageScorer:
    """Second workload. Exists to prove the seam: no core file changes."""

    name = "support_triage_scorer/v1"
    metrics = ("extraction_f1",)

    def score(self, run: dict[str, Any]) -> dict[str, Any]:
        art = run.get("artifacts")
        if not art:
            raise ValueError(f"run {run.get('doc_id')!r} has no recorded artifacts")
        tp, fp, fn = art["true_positives"], art["false_positives"], art["false_negatives"]
        denom = 2 * tp + fp + fn
        if denom == 0:
            raise ValueError(f"run {run.get('doc_id')!r} has an empty label set")
        f1 = (2 * tp) / denom
        return {
            "quality_scores": {"extraction_f1": round(f1, 4)},
            "succeeded": f1 >= 0.70,
            "failure_reason": None if f1 >= 0.70 else "extraction_f1_below_review_threshold",
            "human_rework_minutes": float(art["human_rework_minutes"]),
        }


CONTRACT_ANALYSIS_SCORER = ContractAnalysisScorer()
SUPPORT_TRIAGE_SCORER = SupportTriageScorer()


def register_all() -> None:
    register_cost_meter("contract_analysis", TOKEN_COST_METER)
    register_scorer("contract_analysis", CONTRACT_ANALYSIS_SCORER)
    register_cost_meter("support_triage", TOKEN_COST_METER)
    register_scorer("support_triage", SUPPORT_TRIAGE_SCORER)
