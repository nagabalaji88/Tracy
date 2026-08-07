"""
TokenCostMeter — the default CostMeter.

Cost is token counts (recorded) x rates (configured in pricing.yaml). It is the
only place in the system allowed to turn tokens into dollars.
"""

from __future__ import annotations

from typing import Any

from app.policy import model_pricing

_PER_MILLION = 1_000_000.0
_REQUIRED = ("input_tokens_fresh", "input_tokens_cached", "output_tokens", "reasoning_tokens")


class TokenCostMeter:
    name = "token_cost_meter/v1"

    def cost_usd(self, span: dict[str, Any]) -> float:
        model = span.get("model")
        if not model:
            raise ValueError(f"span {span.get('span_id')!r} has no model; refusing to cost it")
        missing = [k for k in _REQUIRED if span.get(k) is None]
        if missing:
            raise ValueError(
                f"span {span.get('span_id')!r} missing token counts {missing}; "
                "refusing to substitute zeros"
            )
        rates = model_pricing(model)
        cost = (
            span["input_tokens_fresh"] * rates["fresh_input"]
            + span["input_tokens_cached"] * rates["cached_input"]
            + span["output_tokens"] * rates["output"]
            + span["reasoning_tokens"] * rates["reasoning"]
        ) / _PER_MILLION
        if span.get("batch_api"):
            cost *= rates["batch_multiplier"]
        return round(cost, 8)

    def projected_cost_usd(self, span_shape: dict[str, Any]) -> float:
        """Heuristic. Every number derived from this is labelled 'projected'."""
        return self.cost_usd(span_shape)


TOKEN_COST_METER = TokenCostMeter()
