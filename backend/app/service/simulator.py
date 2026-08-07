"""
MODULE 4 — the optimisation simulator.

Everything this module produces is a PROJECTION, and every number leaving it
carries `is_projection: true`.

The single-lever effects underneath are not guesses: they were measured by
running the golden set with one lever changed and everything else held at
baseline (`harness/calibrate_levers.py`). What remains approximate is the
composition — the simulator multiplies those effects as if levers were
independent, and they are not. When a lever combination matches a fully recorded
configuration, the measured result is returned beside the projection along with
the projection's error, which is the honest measure of how far this screen can be
trusted.

The other job here is pre-flight: a lever whose projected quality would breach a
floor is flagged before the run, not after the invoice.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Sequence

from app.policy import floor_violation, metric_label
from app.service.measurement import MeasurementError

LEVER_EFFECTS_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "lever_effects.json"


@functools.lru_cache(maxsize=1)
def load_effects() -> dict[str, Any]:
    if not LEVER_EFFECTS_PATH.exists():
        raise MeasurementError(
            f"lever effects not calibrated ({LEVER_EFFECTS_PATH} missing). "
            "Run `python -m harness.calibrate_levers` — the simulator will not "
            "invent multipliers."
        )
    return json.loads(LEVER_EFFECTS_PATH.read_text())


def levers_by_id() -> dict[str, dict[str, Any]]:
    return {lever["id"]: lever for lever in load_effects()["levers"]}


def baseline_lever_values() -> dict[str, Any]:
    return {lever["id"]: lever["default"] for lever in load_effects()["levers"]}


def _key(value: Any) -> str:
    return str(value)


def _coerce(lever: dict[str, Any], value: Any) -> Any:
    for option in lever["options"]:
        if _key(option) == _key(value):
            return option
    raise MeasurementError(
        f"lever '{lever['id']}' has no option '{value}'. Valid: {lever['options']}"
    )


def catalogue(base_config_id: str, measured: dict[str, dict[str, Any]]) -> dict[str, Any]:
    effects = load_effects()
    return {
        "levers": [
            {k: v for k, v in lever.items() if k != "effects"} for lever in effects["levers"]
        ],
        "base_config_id": base_config_id,
        "baseline_levers": baseline_lever_values(),
        "calibration": {
            "provider": effects["provider"],
            "golden_set_size": effects["golden_set_size"],
            "note": effects["note"],
        },
        "measured_configs": measured,
    }


def simulate(
    baseline: dict[str, Any],
    lever_values: dict[str, Any],
    policy: dict[str, Any],
    monthly_documents: float,
    measured_configs: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Project one lever combination against a measured baseline.

    Unspecified levers are filled from the baseline configuration, so a selection
    is always a complete configuration — which is what makes matching it against
    a recorded run meaningful.
    """
    registry = levers_by_id()
    chosen = baseline_lever_values()
    for lever_id, raw in lever_values.items():
        if lever_id not in registry:
            raise MeasurementError(f"unknown lever '{lever_id}'. Known: {sorted(registry)}")
        chosen[lever_id] = _coerce(registry[lever_id], raw)

    cost_mult = 1.0
    latency_mult = 1.0
    quality = dict(baseline["quality"])
    effects: list[dict[str, Any]] = []

    for lever_id, value in chosen.items():
        lever = registry[lever_id]
        effect = lever["effects"][_key(value)]
        cost_mult *= effect["cost"]
        latency_mult *= effect["latency"]
        for metric, delta in effect["quality"].items():
            if metric not in quality:
                raise MeasurementError(
                    f"lever '{lever_id}' moves '{metric}', which the baseline run set does not "
                    "measure. Refusing to project a metric with no measured starting point."
                )
            quality[metric] = round(quality[metric] + delta, 6)
        effects.append({
            "id": lever_id,
            "label": lever["label"],
            "value": value,
            "is_baseline": value == lever["default"],
            "cost_multiplier": effect["cost"],
            "latency_multiplier": effect["latency"],
            "quality_effect": effect["quality"],
            "rationale": lever["description"],
        })

    projected_cost = baseline["cost_per_document_usd"] * cost_mult
    projected_p95 = round(baseline["latency_ms"]["p95"] * latency_mult)

    floor_risk = []
    for metric, floor in policy["quality_floor"].items():
        if metric not in quality:
            raise MeasurementError(
                f"policy declares a floor on '{metric}' with no measured baseline value"
            )
        value = quality[metric]
        shortfall = floor_violation(metric, value, floor)
        floor_risk.append({
            "metric": metric,
            "label": metric_label(metric),
            "floor": floor,
            "projected_value": round(value, 4),
            "baseline_value": baseline["quality"][metric],
            "breaches": shortfall is not None,
            "margin": round(-(shortfall or 0.0), 6) if shortfall is not None
                      else round(abs(value - floor), 6),
        })

    ceiling = policy["latency_ceiling_ms"]
    latency_risk = {
        "projected_p95_ms": projected_p95,
        "ceiling_ms": ceiling,
        "breaches": projected_p95 > ceiling,
    }

    reasons = [
        f"{r['label']} projected at {r['projected_value']:.4g} against a floor of {r['floor']:.4g}"
        for r in floor_risk if r["breaches"]
    ]
    if latency_risk["breaches"]:
        reasons.append(f"projected p95 latency {projected_p95} ms exceeds the {ceiling} ms ceiling")

    match = _find_measured_match(chosen, measured_configs or [], projected_cost)

    return {
        "chosen_levers": {k: v for k, v in chosen.items()},
        "basis": {
            "config_id": baseline["config_id"],
            "measured_cost_per_document_usd": baseline["cost_per_document_usd"],
            "n_documents": baseline["n_documents"],
        },
        "projected": {
            "cost_per_document_usd": round(projected_cost, 6),
            "monthly_spend_usd": round(projected_cost * monthly_documents, 2),
            "pct_change": round((cost_mult - 1) * 100, 2),
            "latency_p95_ms": projected_p95,
            "quality_estimate": {k: round(v, 4) for k, v in quality.items()},
            "is_projection": True,
        },
        "lever_effects": effects,
        "floor_risk": floor_risk,
        "latency_risk": latency_risk,
        "preflight": {"blocked": bool(reasons), "reasons": reasons},
        "measured_match": match,
        "disclaimer": (
            "Projected, not measured. Single-lever effects were measured on the golden set; "
            "composing them assumes independence they do not have. Record the configuration and "
            "evaluate it in Module 1 before promoting anything on the strength of this screen."
        ),
    }


# How a recorded configuration's levers map onto the simulator's lever vocabulary.
_CONFIG_LEVER_READERS = {
    "model_tier": lambda lv: lv.get("model_by_stage", {}).get("clause_extract"),
    "risk_tier": lambda lv: lv.get("model_by_stage", {}).get("risk_assess"),
    "synthesis_tier": lambda lv: lv.get("model_by_stage", {}).get("synthesize"),
    "prompt_caching": lambda lv: bool(lv.get("prompt_cache")),
    "top_k": lambda lv: lv.get("top_k"),
    "output_cap": lambda lv: lv.get("output_cap"),
    "batch_api": lambda lv: bool(lv.get("batch_stages")),
    "semantic_cache": lambda lv: bool(lv.get("semantic_cache")),
}


def _find_measured_match(chosen: dict[str, Any], measured: Sequence[dict[str, Any]],
                         projected_cost: float) -> dict[str, Any] | None:
    """
    Has this exact configuration actually been run?

    Every lever must agree — a partial match would put a projection next to a
    measurement of something else and call the difference "error".
    """
    for candidate in measured:
        levers = candidate["levers"]
        if all(
            _key(reader(levers)) == _key(chosen[lever_id])
            for lever_id, reader in _CONFIG_LEVER_READERS.items()
            if lever_id in chosen
        ):
            measured_cost = candidate["measured"]["cost_per_document_usd"]
            return {
                "config_id": candidate["config_id"],
                "label": candidate["label"],
                "measured_cost_per_document_usd": measured_cost,
                "measured_quality": candidate["measured"]["quality"],
                "measured_latency_p95_ms": candidate["measured"]["latency_ms"]["p95"],
                "decision": candidate.get("decision", "not_evaluated"),
                "projection_error_pct": round(
                    (projected_cost - measured_cost) / measured_cost * 100, 2),
            }
    return None
