"""
The ATLAS adapter — the whole cost of onboarding an agent this control plane did
not build.

ATLAS is a separate application on a separate port with its own store. It does
not import this package and this package does not import it. All that passes
between them is a JSON document in ATLAS's own shape.

Two things live here, and nothing else changes anywhere in the core:

  AtlasScorer      the Scorer protocol — recorded artifacts in, quality scores
                   and a success verdict out.
  ingest_records   maps ATLAS's debug record onto the trace/outcome spine.

The CostMeter is reused unchanged: ATLAS reports token counts per model, which
is all TokenCostMeter has ever needed. Note what that fixes on its own — ATLAS's
own cost figure is a flat $0.004/1k applied to every model (its flaw F01), and
re-pricing the same recorded tokens per model is the entire correction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.adapters.base import register_cost_meter, register_scorer
from app.adapters.token_cost_meter import TOKEN_COST_METER

USE_CASE = "equity_research_memo"

# ATLAS stage -> the cost bucket the control plane accounts it under. ATLAS has
# no concept of a cost bucket; this is the adapter supplying one.
STAGE_BUCKETS = {
    "fetch_filings": "embedding",
    "peer_comparison": "tool",
}


class AtlasScorer:
    """
    Quality for an ATLAS run, computed from what ATLAS already recorded.

    Everything below is arithmetic over artifacts the agent produced and threw
    away: it extracted 60 of 186 tagged figures and knew both numbers; it read a
    finish_reason of "length" and ignored it. Nothing here is inferred, and
    nothing is invented — a missing artifact raises.
    """

    name = "atlas_scorer/v1"
    metrics = ("figure_accuracy", "disclosure_recall", "citation_accuracy", "truncation_rate")
    REVIEW_THRESHOLD = 0.60

    REQUIRED = (
        "gold_figures", "figures_extracted", "gold_disclosures", "disclosures_flagged",
        "citations_checked", "citations_correct", "memo_truncated", "analyst_rework_minutes",
    )

    def score(self, run: dict[str, Any]) -> dict[str, Any]:
        art = run.get("artifacts")
        if not art:
            raise ValueError(f"ATLAS run {run.get('doc_id')!r} has no artifacts; refusing to score")
        missing = [k for k in self.REQUIRED if k not in art]
        if missing:
            raise ValueError(f"ATLAS run {run.get('doc_id')!r} artifact missing {missing}")
        if art["gold_figures"] <= 0 or art["gold_disclosures"] <= 0:
            raise ValueError(f"ATLAS run {run.get('doc_id')!r} has an empty gold reference")
        if art["citations_checked"] <= 0:
            raise ValueError(f"ATLAS run {run.get('doc_id')!r} recorded zero citation checks")

        figure_accuracy = art["figures_extracted"] / art["gold_figures"]
        disclosure_recall = art["disclosures_flagged"] / art["gold_disclosures"]
        citation_accuracy = art["citations_correct"] / art["citations_checked"]
        truncated = bool(art["memo_truncated"])

        scores = {
            "figure_accuracy": round(figure_accuracy, 4),
            "disclosure_recall": round(disclosure_recall, 4),
            "citation_accuracy": round(citation_accuracy, 4),
            "truncation_rate": 1.0 if truncated else 0.0,
        }

        # ATLAS's success test is "nothing raised". This one is "the analyst could
        # send it". A truncated memo cannot go to a client; a memo that missed a
        # third of the disclosure items is a compliance problem, not a draft.
        failure_reason = None
        if truncated:
            failure_reason = "memo_truncated"
        elif disclosure_recall < self.REVIEW_THRESHOLD:
            failure_reason = "disclosure_recall_below_review_threshold"
        elif figure_accuracy < self.REVIEW_THRESHOLD:
            failure_reason = "figure_accuracy_below_review_threshold"

        return {
            "quality_scores": scores,
            "succeeded": failure_reason is None,
            "failure_reason": failure_reason,
            "human_rework_minutes": float(art["analyst_rework_minutes"]),
        }


ATLAS_SCORER = AtlasScorer()


def _outcome_id(run_id: str) -> str:
    return f"OUT-{run_id}"


def _iso(value: str) -> str:
    # ATLAS writes millisecond precision; the store keeps second precision.
    return datetime.fromisoformat(value).replace(microsecond=0).isoformat()


def _config_id(profile: str) -> str:
    return f"atlas_{profile}"


def ingest_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Map ATLAS debug records onto the spine.

    ATLAS carries none of: trace ids, cost, outcomes, environments, prompt
    versions, cost buckets, or a policy. Every one of those is supplied here, from
    fields ATLAS does record. That mapping is the adapter's whole job.
    """
    if not records:
        raise ValueError("no ATLAS runs supplied; nothing to ingest")

    traces: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    profiles: set[str] = set()

    for record in records:
        for field in ("run_id", "ticker", "profile", "spans", "artifacts"):
            if field not in record:
                raise ValueError(
                    f"ATLAS record missing '{field}'. Refusing to ingest a partial run — "
                    "a trace with no spans would silently become a zero-cost outcome."
                )
        if not record["spans"]:
            raise ValueError(f"ATLAS run {record['run_id']} has no spans")

        profile = record["profile"]
        profiles.add(profile)
        run_id = record["run_id"]
        outcome_id = _outcome_id(run_id)
        # ATLAS has no environment concept for runs it did not tag. Anything the
        # evaluation harness drove is 'eval'; everything else is live traffic.
        environment = record.get("environment", "production")
        # Nor does it version prompts (each stage's prompt is a string literal in
        # the module). The application version is the closest honest proxy, and
        # labelling it as such is better than inventing a version number.
        prompt_version = record.get("source_version", "atlas-3.2.1")

        parent = None
        for span in record["spans"]:
            retry_index = span.get("retry_index", 0)
            bucket = "retry" if retry_index > 0 else STAGE_BUCKETS.get(span["stage"], "inference")
            row = {
                "span_id": span["span_id"],
                "trace_id": run_id,
                "parent_span_id": parent,
                "stage": span["stage"],
                "tenant": record.get("mandate", "unknown"),
                "team": record.get("desk", "unknown"),
                "use_case": USE_CASE,
                "environment": environment,
                "prompt_version": prompt_version,
                "config_id": _config_id(profile),
                "doc_id": record["ticker"],
                "gen_ai_system": "anthropic",
                "model": span["model"],
                "response_model": span["model"],
                "input_tokens_fresh": span["input_tokens"],
                # ATLAS never enables prompt caching, so this is structurally zero.
                # That zero is a finding, not a gap: it is what the cached-vs-fresh
                # panel reports and what the caching lever is priced against.
                "input_tokens_cached": span.get("cached_input_tokens", 0),
                "output_tokens": span["output_tokens"],
                "reasoning_tokens": span.get("reasoning_tokens", 0),
                "max_output_tokens": None,
                "temperature": 0.0,
                "finish_reason": span.get("finish_reason"),
                "retry_index": retry_index,
                "agent_depth": span.get("depth", 1),
                "call_fingerprint": span.get("fingerprint"),
                "batch_api": 0,
                "cost_bucket": bucket,
                "latency_ms": span["latency_ms"],
                "outcome_id": outcome_id,
                "started_at": _iso(span["at"]),
            }
            row["cost_usd"] = TOKEN_COST_METER.cost_usd(row)
            traces.append(row)
            if retry_index == 0:
                parent = span["span_id"]

        scored = ATLAS_SCORER.score({"doc_id": record["ticker"], "artifacts": record["artifacts"]})
        import json

        outcomes.append({
            "outcome_id": outcome_id,
            "use_case": USE_CASE,
            "config_id": _config_id(profile),
            "environment": environment,
            "tenant": record.get("mandate", "unknown"),
            "team": record.get("desk", "unknown"),
            "prompt_version": prompt_version,
            "doc_id": record["ticker"],
            "doc_tier": record.get("sector", "unknown"),
            "succeeded": 1 if scored["succeeded"] else 0,
            "failure_reason": scored["failure_reason"],
            "quality_scores": json.dumps(scored["quality_scores"]),
            "human_rework_minutes": scored["human_rework_minutes"],
            "timestamp": _iso(record["spans"][0]["at"]),
        })

    import json

    configs = [
        {
            "config_id": _config_id(p),
            "use_case": USE_CASE,
            "label": "ATLAS standard" if p == "standard" else "ATLAS cost-optimized",
            # The profile in production longest is the baseline everything else is
            # compared against. ATLAS has no opinion on this; the control plane does.
            "role": "baseline" if p == "standard" else "candidate",
            "ablated_stage": None,
            "levers": json.dumps({"profile": p, "source": "atlas"}),
            "recorded_at": min(o["timestamp"] for o in outcomes),
        }
        for p in sorted(profiles)
    ]

    return {"traces": traces, "outcomes": outcomes, "configs": configs}


def digest(records: list[dict[str, Any]]) -> str:
    """Stable id for a batch, so re-posting the same runs is idempotent."""
    payload = "".join(sorted(r["run_id"] for r in records))
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def register() -> None:
    register_cost_meter(USE_CASE, TOKEN_COST_METER)
    register_scorer(USE_CASE, ATLAS_SCORER)
