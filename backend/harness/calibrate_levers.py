"""
Calibrate the simulator's lever table by measuring one lever at a time.

The Module 4 simulator is a projection, but the numbers underneath it do not have
to be guesses. For every lever value, this runs the golden set under
baseline-with-that-one-lever-changed and records what actually happened to cost,
latency and quality.

What stays approximate is the composition: the simulator multiplies single-lever
effects as if they were independent, and they are not. That residual error is
exactly what the "measured vs projected" panel shows when a lever combination
happens to match a fully recorded configuration.

Run:  python -m harness.calibrate_levers
Out:  fixtures/lever_effects.json
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.adapters import get_cost_meter, get_scorer
from app.service.measurement import aggregate_quality
from app.service.stats import percentile
from harness.golden_set import GOLDEN_SET
from harness.workload import BASELINE, Config
from harness.providers import get_provider

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# lever id -> how it changes a Config, and the values worth measuring.
LEVER_SPECS: list[dict[str, Any]] = [
    {
        "id": "model_tier",
        "label": "Model tier (extraction stage)",
        "kind": "choice",
        "options": ["premium-reasoning", "workhorse", "small-fast"],
        "baseline_value": BASELINE.model_by_stage["clause_extract"],
        "apply": lambda c, v: replace(c, model_by_stage={**c.model_by_stage, "clause_extract": v}),
        "description": "The model doing clause extraction. The largest cost lever and the "
                       "largest quality lever at once.",
        "affects": ["cost", "quality", "latency"],
    },
    {
        "id": "risk_tier",
        "label": "Model tier (risk assessment)",
        "kind": "choice",
        "options": ["premium-reasoning", "workhorse", "small-fast"],
        "baseline_value": BASELINE.model_by_stage["risk_assess"],
        "apply": lambda c, v: replace(c, model_by_stage={**c.model_by_stage, "risk_assess": v}),
        "description": "Reasoning over extracted clauses. Cheap to downgrade, and it is the "
                       "stage that verifies citations.",
        "affects": ["cost", "quality", "latency"],
    },
    {
        "id": "synthesis_tier",
        "label": "Model tier (synthesis)",
        "kind": "choice",
        "options": ["premium-reasoning", "workhorse", "small-fast"],
        "baseline_value": BASELINE.model_by_stage["synthesize"],
        "apply": lambda c, v: replace(c, model_by_stage={**c.model_by_stage, "synthesize": v}),
        "description": "Writing the review memo. Structured, low-variance work — the safest "
                       "stage to move down a tier.",
        "affects": ["cost", "latency"],
    },
    {
        "id": "prompt_caching",
        "label": "Prompt caching",
        "kind": "toggle",
        "options": [True, False],
        "baseline_value": BASELINE.prompt_cache,
        "apply": lambda c, v: replace(c, prompt_cache=bool(v)),
        "description": "Cache the shared contract preamble across sections and stages. "
                       "Quality-neutral by construction: the tokens are identical.",
        "affects": ["cost"],
    },
    {
        "id": "top_k",
        "label": "Retrieval top-k",
        "kind": "choice",
        "options": [3, 6, 9, 12, 16],
        "baseline_value": BASELINE.top_k,
        "apply": lambda c, v: replace(c, top_k=int(v)),
        "description": "Supporting passages retrieved per section. Cutting this looks nearly "
                       "free on the invoice and is not free on recall — the exact trap the "
                       "naive-cheap configuration fell into.",
        "affects": ["cost", "quality"],
    },
    {
        "id": "output_cap",
        "label": "Output cap",
        "kind": "choice",
        "options": [1200, 2000, 3000, 4000],
        "baseline_value": BASELINE.output_cap,
        "apply": lambda c, v: replace(c, output_cap=int(v)),
        "description": "Maximum memo length. Below what long contracts need the memo truncates, "
                       "and truncation is a floor with zero tolerance.",
        "affects": ["cost", "quality"],
    },
    {
        "id": "batch_api",
        "label": "Batch API for synthesis",
        "kind": "toggle",
        "options": [True, False],
        "baseline_value": bool(BASELINE.batch_stages),
        "apply": lambda c, v: replace(c, batch_stages=("synthesize",) if v else ()),
        "description": "Half price on the non-interactive stage at roughly three times its "
                       "latency. Quality-neutral; what it threatens is the ceiling.",
        "affects": ["cost", "latency"],
    },
    {
        "id": "semantic_cache",
        "label": "Semantic cache on retrieval",
        "kind": "toggle",
        "options": [True, False],
        "baseline_value": BASELINE.semantic_cache,
        "apply": lambda c, v: replace(c, semantic_cache=bool(v)),
        "description": "Reuse retrieval for documents already analysed. Saves very little here "
                       "because embedding is a rounding error — measured, so we can say so.",
        "affects": ["cost"],
    },
]


def _measure(config: Config, provider) -> dict[str, Any]:
    """
    Run the golden set under one configuration and summarise it.

    The seed key deliberately ignores the config id, so every variant replays the
    SAME underlying runs with one lever changed. Anything else would let seed
    noise — a retry that fired in one variant and not another — masquerade as a
    lever effect, and on 24 documents that noise is the same size as the effects
    being measured.
    """
    meter = get_cost_meter("contract_analysis")
    scorer = get_scorer("contract_analysis")
    total = 0.0
    latencies: list[float] = []
    outcomes: list[dict] = []
    for doc in GOLDEN_SET:
        seed_key = f"calibration/{doc.doc_id}"
        result = provider.run(doc, config, seed_key)
        doc_latency = 0
        for span in result["spans"]:
            row = dict(span, batch_api=span.get("batch_api", 0))
            total += meter.cost_usd(row)
            doc_latency += row["latency_ms"]
        latencies.append(doc_latency)
        scored = scorer.score({"doc_id": doc.doc_id, "artifacts": result["artifacts"]})
        outcomes.append({
            "outcome_id": doc.doc_id,
            "quality_scores": scored["quality_scores"],
            "succeeded": scored["succeeded"],
            "human_rework_minutes": scored["human_rework_minutes"],
        })
    return {
        "cost_usd": total,
        "cost_per_document_usd": total / len(GOLDEN_SET),
        "latency_p95_ms": percentile(latencies, 95),
        "quality": aggregate_quality(outcomes),
    }


def calibrate(provider_kind: str = "deterministic") -> dict[str, Any]:
    provider = get_provider(provider_kind)
    # Every lever is measured against the SAME baseline recording, so multipliers
    # are comparable to each other.
    base = _measure(BASELINE, provider)

    levers: list[dict[str, Any]] = []
    for spec in LEVER_SPECS:
        effects: dict[str, Any] = {}
        for value in spec["options"]:
            variant = spec["apply"](replace(BASELINE, config_id=f"cal_{spec['id']}_{value}"), value)
            m = _measure(variant, provider)
            effects[str(value)] = {
                "cost": round(m["cost_per_document_usd"] / base["cost_per_document_usd"], 6),
                "latency": round(m["latency_p95_ms"] / base["latency_p95_ms"], 6),
                "quality": {
                    metric: round(m["quality"][metric] - base["quality"][metric], 6)
                    for metric in base["quality"]
                    if metric in m["quality"]
                    and abs(m["quality"][metric] - base["quality"][metric]) > 1e-9
                },
                "measured_cost_per_document_usd": round(m["cost_per_document_usd"], 6),
            }
        levers.append({
            "id": spec["id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "options": spec["options"],
            "default": spec["baseline_value"],
            "description": spec["description"],
            "affects": spec["affects"],
            "effects": effects,
        })

    doc = {
        "provider": provider.name,
        "baseline_config_id": BASELINE.config_id,
        "baseline": {
            "cost_per_document_usd": round(base["cost_per_document_usd"], 6),
            "latency_p95_ms": round(base["latency_p95_ms"]),
            "quality": base["quality"],
        },
        "golden_set_size": len(GOLDEN_SET),
        "levers": levers,
        "note": (
            "Each lever value was measured by running the full golden set with that one lever "
            "changed and everything else held at baseline. The simulator composes them "
            "multiplicatively, which assumes independence they do not have — that residual is "
            "why every simulated number is labelled projected."
        ),
    }
    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "lever_effects.json").write_text(json.dumps(doc, indent=2))
    return doc


if __name__ == "__main__":
    result = calibrate()
    print(f"calibrated {len(result['levers'])} levers against "
          f"{result['golden_set_size']} golden documents")
    for lever in result["levers"]:
        for value, eff in lever["effects"].items():
            q = " ".join(f"{m}{d:+.3f}" for m, d in eff["quality"].items())
            print(f"  {lever['id']:16s} {value:<18} cost x{eff['cost']:.3f} "
                  f"lat x{eff['latency']:.3f}  {q}")
