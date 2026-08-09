"""
Loader for policy.yaml and pricing.yaml.

Fails loudly. A missing use case, a missing metric direction, or a missing model
price is an exception — never a default. Silent defaults in a control plane are
how a quality floor quietly stops being enforced.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
POLICY_PATH = BACKEND_DIR / "policy.yaml"
PRICING_PATH = BACKEND_DIR / "pricing.yaml"


class PolicyError(RuntimeError):
    """Raised when the policy contract cannot answer a question it must answer."""


@functools.lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    if not POLICY_PATH.exists():
        raise PolicyError(f"policy.yaml not found at {POLICY_PATH}")
    with POLICY_PATH.open() as fh:
        doc = yaml.safe_load(fh)
    for required in ("use_cases", "metrics", "economics", "significance"):
        if required not in doc:
            raise PolicyError(f"policy.yaml missing required top-level key '{required}'")
    return doc


@functools.lru_cache(maxsize=1)
def load_pricing() -> dict[str, Any]:
    if not PRICING_PATH.exists():
        raise PolicyError(f"pricing.yaml not found at {PRICING_PATH}")
    with PRICING_PATH.open() as fh:
        doc = yaml.safe_load(fh)
    if "models" not in doc:
        raise PolicyError("pricing.yaml missing 'models'")
    return doc


def reload() -> None:
    load_policy.cache_clear()
    load_pricing.cache_clear()


def use_case_policy(use_case: str) -> dict[str, Any]:
    policy = load_policy()
    try:
        return policy["use_cases"][use_case]
    except KeyError:
        known = ", ".join(sorted(policy["use_cases"]))
        raise PolicyError(
            f"use_case '{use_case}' is not declared in policy.yaml. Known: {known}. "
            "Onboarding a workload means adding a policy entry, not editing the core."
        ) from None


def metric_direction(metric: str) -> str:
    """'higher_is_better' | 'lower_is_better'. Never guessed."""
    metrics = load_policy()["metrics"]
    if metric not in metrics:
        raise PolicyError(
            f"metric '{metric}' has no declared direction in policy.yaml:metrics. "
            "Refusing to guess whether higher or lower is better."
        )
    direction = metrics[metric].get("direction")
    if direction not in ("higher_is_better", "lower_is_better"):
        raise PolicyError(f"metric '{metric}' has invalid direction '{direction}'")
    return direction


def metric_label(metric: str) -> str:
    metrics = load_policy()["metrics"]
    if metric not in metrics:
        raise PolicyError(f"metric '{metric}' is not declared in policy.yaml:metrics")
    return metrics[metric].get("label", metric)


def model_pricing(model: str) -> dict[str, float]:
    models = load_pricing()["models"]
    if model not in models:
        raise PolicyError(
            f"no price for model '{model}' in pricing.yaml. Refusing to cost a run "
            "with an assumed rate."
        )
    return models[model]


def rework_hourly_rate() -> float:
    return float(load_policy()["economics"]["human_rework_hourly_rate_usd"])


def significance_settings() -> dict[str, Any]:
    return load_policy()["significance"]


def floor_violation(metric: str, value: float, floor: float) -> float | None:
    """
    Return the shortfall magnitude if `value` violates `floor`, else None.

    Direction comes from policy, never from the metric's name.
    """
    direction = metric_direction(metric)
    if direction == "higher_is_better":
        return round(floor - value, 6) if value < floor else None
    return round(value - floor, 6) if value > floor else None
