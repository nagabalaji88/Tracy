"""
Adapter interfaces — the extension seam.

Onboarding a second workload = one `policy.yaml` entry + these two protocols.
The measurement core, attribution, forecast, simulator and breakers never import
a workload-specific module; they resolve adapters through the registry below.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CostMeter(Protocol):
    """Turns recorded token usage into money. Pure function of the span."""

    name: str

    def cost_usd(self, span: dict[str, Any]) -> float:
        """
        Cost of a single recorded span in USD.

        MUST fail loudly (raise) on an unknown model or missing token counts.
        MUST NOT invent token counts.
        """
        ...

    def projected_cost_usd(self, span_shape: dict[str, Any]) -> float:
        """
        Cost of a hypothetical span for the simulator. Heuristic by definition —
        anything derived from this is labelled 'projected' in the UI.
        """
        ...


@runtime_checkable
class Scorer(Protocol):
    """
    Turns a recorded run into quality scores and a success verdict.

    A Scorer may only read what was recorded. If a metric was not measured for a
    run it must be absent from the returned dict — never zero, never a guess.
    """

    name: str
    metrics: tuple[str, ...]

    def score(self, run: dict[str, Any]) -> dict[str, Any]:
        """
        Returns:
            {
              "quality_scores": {metric: float, ...},
              "succeeded": bool,
              "failure_reason": str | None,
              "human_rework_minutes": float,
            }
        """
        ...


_COST_METERS: dict[str, CostMeter] = {}
_SCORERS: dict[str, Scorer] = {}


def register_cost_meter(use_case: str, meter: CostMeter) -> None:
    _COST_METERS[use_case] = meter


def register_scorer(use_case: str, scorer: Scorer) -> None:
    _SCORERS[use_case] = scorer


def get_cost_meter(use_case: str) -> CostMeter:
    if use_case not in _COST_METERS:
        raise LookupError(
            f"no CostMeter registered for use_case '{use_case}'. "
            "Implement the CostMeter protocol and register it — do not edit the core."
        )
    return _COST_METERS[use_case]


def get_scorer(use_case: str) -> Scorer:
    if use_case not in _SCORERS:
        raise LookupError(
            f"no Scorer registered for use_case '{use_case}'. "
            "Implement the Scorer protocol and register it — do not edit the core."
        )
    return _SCORERS[use_case]


def registered() -> dict[str, dict[str, str]]:
    use_cases = set(_COST_METERS) | set(_SCORERS)
    return {
        uc: {
            "cost_meter": getattr(_COST_METERS.get(uc), "name", None),
            "scorer": getattr(_SCORERS.get(uc), "name", None),
            "metrics": list(getattr(_SCORERS.get(uc), "metrics", ())),
        }
        for uc in sorted(use_cases)
    }
