"""
The recording session.

Produces the fixtures the demo replays:

  fixtures/configs.json        the configurations that were recorded
  fixtures/traces.json         every span, for every run
  fixtures/outcomes.json       one business outcome per run, scored by a Scorer
  fixtures/runaway_trace.json  the trace Module 5 replays through the breakers

Run:
    python -m harness.record_runs                 # deterministic, replays exactly
    python -m harness.record_runs --provider live # real calls, needs credentials

Everything written here is DATA. The measurement core reads it and cannot tell
which provider produced it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters import get_cost_meter, get_scorer
from harness.golden_set import GOLDEN_SET, GoldenDoc, _jitter
from harness.providers import _fingerprint, _u, get_provider
from harness.workload import (
    BASELINE,
    CONFIG_BY_ID,
    EVAL_CONFIGS,
    PROMPT_DEPLOYS,
    Config,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

REFERENCE_DATE = datetime(2026, 8, 7, tzinfo=timezone.utc)
PRODUCTION_DAYS = 45

TENANTS = ("acme-legal", "globex-corp")
TEAMS = ("legal-ops", "procurement", "risk-review")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _trace_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:32]


def _span_id(trace_id: str, i: int) -> str:
    return hashlib.sha1(f"{trace_id}:{i}".encode()).hexdigest()[:16]


def _assign(doc_id: str, options: tuple[str, ...]) -> str:
    return options[int(hashlib.sha256(doc_id.encode()).hexdigest(), 16) % len(options)]


def _materialise(
    *,
    doc: GoldenDoc,
    config: Config,
    environment: str,
    prompt_version: str,
    started: datetime,
    provider,
    use_case: str = "contract_analysis",
) -> tuple[list[dict], dict]:
    """Run one document and turn the result into trace rows plus one outcome row."""
    seed_key = f"{config.config_id}/{doc.doc_id}/{prompt_version}"
    cfg = replace(config, prompt_version=prompt_version)
    result = provider.run(doc, cfg, seed_key)

    meter = get_cost_meter(use_case)
    scorer = get_scorer(use_case)

    trace_id = _trace_id(config.config_id, doc.doc_id, environment, prompt_version)
    outcome_id = f"OUT-{trace_id[:12]}"
    tenant = _assign(doc.doc_id, TENANTS)
    team = _assign(doc.doc_id + "team", TEAMS)

    rows: list[dict] = []
    parent = None
    clock = started
    for i, span in enumerate(result["spans"]):
        row = dict(span)
        span_id = _span_id(trace_id, i)
        row.update(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent,
            tenant=tenant,
            team=team,
            use_case=use_case,
            environment=environment,
            prompt_version=prompt_version,
            config_id=config.config_id,
            doc_id=doc.doc_id,
            outcome_id=outcome_id,
            started_at=_iso(clock),
        )
        row["cost_usd"] = meter.cost_usd(row)
        clock += timedelta(milliseconds=row["latency_ms"])
        if row["retry_index"] == 0:
            parent = span_id
        rows.append(row)

    scored = scorer.score({"doc_id": doc.doc_id, "artifacts": result["artifacts"]})
    outcome = {
        "outcome_id": outcome_id,
        "use_case": use_case,
        "config_id": config.config_id,
        "environment": environment,
        "tenant": tenant,
        "team": team,
        "prompt_version": prompt_version,
        "doc_id": doc.doc_id,
        "doc_tier": doc.tier,
        "succeeded": 1 if scored["succeeded"] else 0,
        "failure_reason": scored["failure_reason"],
        "quality_scores": json.dumps(scored["quality_scores"]),
        "human_rework_minutes": scored["human_rework_minutes"],
        "timestamp": _iso(started),
    }
    return rows, outcome


# --- production document stream ----------------------------------------------
def _production_docs(day: int) -> list[GoldenDoc]:
    """
    Production traffic: mostly standard contracts, with the same hard tail the
    golden set oversamples — just at its real frequency.
    """
    weekday = (REFERENCE_DATE - timedelta(days=PRODUCTION_DAYS - 1 - day)).weekday()
    base = 34 if weekday < 5 else 9
    growth = 1.0 + 0.006 * day
    # A second tenant onboards over the final fortnight. Volume is a driver in
    # its own right — Module 3 projects it separately rather than fitting a
    # trend line through the blended aggregate.
    ramp = 1.0 + 2.1 * max(0.0, min(1.0, (day - 32) / 12.0))
    volume = max(3, int(base * growth * ramp * (0.80 + 0.40 * _u(f"vol/{day}"))))
    docs: list[GoldenDoc] = []
    for i in range(volume):
        doc_id = f"PROD-{day:02d}-{i:03d}"
        r = _u(f"tier/{doc_id}")
        if r < 0.62:
            tier, pages, struct = "standard", (12, 42), (0.0, 0.12)
        elif r < 0.86:
            tier, pages, struct = "long", (90, 240), (0.08, 0.30)
        else:
            tier, pages, struct = "non_standard", (20, 130), (0.40, 0.85)
        p = int(pages[0] + _jitter(f"{doc_id}/p", 0, 1) * (pages[1] - pages[0]))
        clause_count = max(8, int(p * 0.55 * _jitter(f"{doc_id}/c", 0.7, 1.25)))
        docs.append(
            GoldenDoc(
                doc_id=doc_id,
                tier=tier,
                pages=p,
                doc_tokens=p * 620,
                clause_count=clause_count,
                structure_penalty=round(_jitter(f"{doc_id}/s", struct[0], struct[1]), 4),
                gold_clause_ids=tuple(f"{doc_id}::C{j:03d}" for j in range(1, clause_count + 1)),
            )
        )
    return docs


def _prompt_version_for_day(day: int) -> str:
    version = PROMPT_DEPLOYS[0][0]
    for name, start_day in PROMPT_DEPLOYS:
        if day >= start_day:
            version = name
    return version


# --- the runaway trace --------------------------------------------------------
def build_runaway_trace() -> dict:
    """
    A recursive tool loop with a growing context window. The agent re-reads the
    accumulated transcript on every hop, so input tokens grow superlinearly while
    each individual call looks unremarkable.

    Recorded as a normal trace. Module 5 replays it span by span through the
    breaker engine — the breakers are not special-cased to this fixture.
    """
    meter = get_cost_meter("contract_analysis")
    trace_id = _trace_id("runaway", "DOC-RUNAWAY", "production")
    start = REFERENCE_DATE - timedelta(days=1, hours=3)
    clock = start
    rows: list[dict] = []
    context = 9_400
    for i in range(46):
        depth = 1 + i // 4
        stage = "tool_call" if i % 4 else "risk_assess"
        model = "premium-reasoning" if stage == "risk_assess" else "workhorse"
        context = int(context * 1.14) + 1_200
        output = 900 + 40 * i
        row = {
            "span_id": _span_id(trace_id, i),
            "trace_id": trace_id,
            "parent_span_id": _span_id(trace_id, i - 1) if i else None,
            "stage": stage,
            "tenant": "acme-legal",
            "team": "risk-review",
            "use_case": "contract_analysis",
            "environment": "production",
            "prompt_version": PROMPT_DEPLOYS[-1][0],
            "config_id": "baseline_v1",
            "doc_id": "DOC-RUNAWAY",
            "gen_ai_system": "anthropic",
            "model": model,
            "response_model": model,
            "input_tokens_fresh": context,
            "input_tokens_cached": 0,
            "output_tokens": output,
            "reasoning_tokens": 320 if stage == "risk_assess" else 0,
            "max_output_tokens": 4000,
            "temperature": 0.0,
            "finish_reason": "tool_use" if stage == "tool_call" else "stop",
            "retry_index": 0,
            "agent_depth": depth,
            # The loop: the same tool is called with the same fingerprint, over
            # and over, because the agent never records that it already did.
            "call_fingerprint": _fingerprint(stage, model, "cv-2026-07-21",
                                             "clause-lookup" if stage == "tool_call" else f"risk-{i}"),
            "batch_api": 0,
            "cost_bucket": "tool" if stage == "tool_call" else "inference",
            "latency_ms": 800 + 30 * i,
            "outcome_id": None,
            "started_at": _iso(clock),
        }
        row["cost_usd"] = meter.cost_usd(row)
        clock += timedelta(milliseconds=row["latency_ms"] + 250)
        rows.append(row)
    return {"trace_id": trace_id, "spans": rows}


def _support_triage_stream(provider) -> tuple[list[dict], list[dict]]:
    """
    The second use case, recorded for real. Proves the seam: this function adds
    no branch to any service module — the adapters do the work.
    """
    meter = get_cost_meter("support_triage")
    scorer = get_scorer("support_triage")
    traces: list[dict] = []
    outcomes: list[dict] = []
    for day in range(PRODUCTION_DAYS - 14, PRODUCTION_DAYS):
        started = REFERENCE_DATE - timedelta(days=PRODUCTION_DAYS - 1 - day)
        for i in range(18):
            ticket = f"TCK-{day:02d}-{i:03d}"
            trace_id = _trace_id("support", ticket)
            outcome_id = f"OUT-{trace_id[:12]}"
            labels = 6 + int(_u(f"{ticket}/n") * 6)
            tp = int(labels * (0.74 + 0.22 * _u(f"{ticket}/q")))
            fp = int((labels - tp) * 0.6)
            fn = labels - tp
            row = {
                "span_id": _span_id(trace_id, 0),
                "trace_id": trace_id,
                "parent_span_id": None,
                "stage": "triage",
                "tenant": "acme-legal",
                "team": "support",
                "use_case": "support_triage",
                "environment": "production",
                "prompt_version": "st-2026-07-02",
                "config_id": "triage_baseline_v1",
                "doc_id": ticket,
                "gen_ai_system": "anthropic",
                "model": "small-fast",
                "response_model": "small-fast",
                "input_tokens_fresh": 2200 + int(_u(f"{ticket}/in") * 3000),
                "input_tokens_cached": 0,
                "output_tokens": 260 + int(_u(f"{ticket}/out") * 300),
                "reasoning_tokens": 0,
                "max_output_tokens": 1024,
                "temperature": 0.0,
                "finish_reason": "stop",
                "retry_index": 0,
                "agent_depth": 1,
                "call_fingerprint": _fingerprint("triage", "small-fast", "st-2026-07-02", ticket),
                "batch_api": 0,
                "cost_bucket": "inference",
                "latency_ms": 900 + int(_u(f"{ticket}/lat") * 2600),
                "outcome_id": outcome_id,
                "started_at": _iso(started),
            }
            row["cost_usd"] = meter.cost_usd(row)
            traces.append(row)
            scored = scorer.score({
                "doc_id": ticket,
                "artifacts": {
                    "true_positives": tp, "false_positives": fp, "false_negatives": fn,
                    "human_rework_minutes": round(1.5 + fn * 1.2, 2),
                },
            })
            outcomes.append({
                "outcome_id": outcome_id, "use_case": "support_triage",
                "config_id": "triage_baseline_v1", "environment": "production",
                "tenant": "acme-legal", "team": "support", "prompt_version": "st-2026-07-02",
                "doc_id": ticket, "doc_tier": "standard",
                "succeeded": 1 if scored["succeeded"] else 0,
                "failure_reason": scored["failure_reason"],
                "quality_scores": json.dumps(scored["quality_scores"]),
                "human_rework_minutes": scored["human_rework_minutes"],
                "timestamp": _iso(started),
            })
    return traces, outcomes


def record(provider_kind: str = "deterministic") -> dict[str, int]:
    provider = get_provider(provider_kind)
    traces: list[dict] = []
    outcomes: list[dict] = []

    # 1. Golden-set evaluation runs: every config over every golden document.
    #    This is what Module 1 compares. Paired by doc_id, by construction.
    eval_start = REFERENCE_DATE - timedelta(days=2)
    for config in EVAL_CONFIGS:
        for i, doc in enumerate(GOLDEN_SET):
            rows, outcome = _materialise(
                doc=doc, config=config, environment="eval",
                prompt_version=PROMPT_DEPLOYS[-1][0],
                started=eval_start + timedelta(minutes=3 * i),
                provider=provider,
            )
            traces.extend(rows)
            outcomes.append(outcome)

    # 2. Production stream, 45 days, with prompt-version deploys along the way.
    for day in range(PRODUCTION_DAYS):
        day_start = REFERENCE_DATE - timedelta(days=PRODUCTION_DAYS - 1 - day)
        prompt_version = _prompt_version_for_day(day)
        docs_today = _production_docs(day)
        # Spread the day's traffic across a 14-hour working window.
        spacing = (14 * 60) / max(1, len(docs_today))
        for i, doc in enumerate(docs_today):
            rows, outcome = _materialise(
                doc=doc, config=BASELINE, environment="production",
                prompt_version=prompt_version,
                started=day_start.replace(hour=7, minute=0) + timedelta(minutes=spacing * i),
                provider=provider,
            )
            traces.extend(rows)
            outcomes.append(outcome)

        # CI/eval spend on deploy days — a cost bucket most tools never attribute.
        if any(start == day for _, start in PROMPT_DEPLOYS):
            for i, doc in enumerate(GOLDEN_SET):
                rows, _ = _materialise(
                    doc=doc, config=BASELINE, environment="ci",
                    prompt_version=prompt_version,
                    started=day_start + timedelta(minutes=2 * i),
                    provider=provider,
                )
                for row in rows:
                    row["cost_bucket"] = "eval"
                    row["outcome_id"] = None
                traces.extend(rows)
            # Embedding regeneration: the whole corpus is re-indexed on a prompt
            # change because chunking is part of the prompt.
            meter = get_cost_meter("contract_analysis")
            for i, doc in enumerate(GOLDEN_SET):
                trace_id = _trace_id("reindex", prompt_version, doc.doc_id)
                row = {
                    "span_id": _span_id(trace_id, 0), "trace_id": trace_id,
                    "parent_span_id": None, "stage": "reindex",
                    "tenant": _assign(doc.doc_id, TENANTS),
                    "team": _assign(doc.doc_id + "team", TEAMS),
                    "use_case": "contract_analysis", "environment": "production",
                    "prompt_version": prompt_version, "config_id": BASELINE.config_id,
                    "doc_id": doc.doc_id, "gen_ai_system": "anthropic",
                    "model": "embedding-small", "response_model": "embedding-small",
                    "input_tokens_fresh": doc.doc_tokens * 46, "input_tokens_cached": 0,
                    "output_tokens": 0, "reasoning_tokens": 0, "max_output_tokens": 0,
                    "temperature": 0.0, "finish_reason": "stop", "retry_index": 0,
                    "agent_depth": 1,
                    "call_fingerprint": _fingerprint("reindex", "embedding-small",
                                                     prompt_version, doc.doc_id),
                    "batch_api": 0, "cost_bucket": "embedding",
                    "latency_ms": 1200, "outcome_id": None,
                    "started_at": _iso(day_start + timedelta(minutes=1)),
                }
                row["cost_usd"] = meter.cost_usd(row)
                traces.append(row)

    # 3. Second use case.
    st_traces, st_outcomes = _support_triage_stream(provider)
    traces.extend(st_traces)
    outcomes.extend(st_outcomes)

    configs = [
        {
            "config_id": c.config_id,
            "use_case": c.use_case,
            "label": c.label,
            "role": c.role,
            "ablated_stage": c.ablated_stage,
            "levers": json.dumps(c.levers()),
            "recorded_at": _iso(eval_start),
        }
        for c in EVAL_CONFIGS
    ] + [{
        "config_id": "triage_baseline_v1", "use_case": "support_triage",
        "label": "Triage baseline", "role": "baseline", "ablated_stage": None,
        "levers": json.dumps({"model_by_stage": {"triage": "small-fast"}}),
        "recorded_at": _iso(eval_start),
    }]

    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "traces.json").write_text(json.dumps(traces))
    (FIXTURES / "outcomes.json").write_text(json.dumps(outcomes))
    (FIXTURES / "configs.json").write_text(json.dumps(configs, indent=2))
    (FIXTURES / "runaway_trace.json").write_text(json.dumps(build_runaway_trace(), indent=2))
    (FIXTURES / "manifest.json").write_text(json.dumps({
        "provider": provider.name,
        "recorded_at": _iso(datetime.now(timezone.utc)),
        "reference_date": _iso(REFERENCE_DATE),
        "golden_set_size": len(GOLDEN_SET),
        "eval_configs": [c.config_id for c in EVAL_CONFIGS],
        "production_days": PRODUCTION_DAYS,
        "n_spans": len(traces),
        "n_outcomes": len(outcomes),
        "note": (
            "Produced by the recording harness. The measurement core reads these "
            "rows and cannot distinguish which provider wrote them."
        ),
    }, indent=2))

    return {"spans": len(traces), "outcomes": len(outcomes), "configs": len(configs)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Record runs into fixtures.")
    parser.add_argument("--provider", default="deterministic", choices=["deterministic", "live"])
    args = parser.parse_args()
    counts = record(args.provider)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
