"""
Model client for ATLAS.

Two implementations behind one interface, same as any production wrapper:

  LiveClient       real API calls; needs ANTHROPIC_API_KEY.
  SimulatedClient  seeded, deterministic, streams in real time so the terminal
                   behaves exactly as it would against a live endpoint.

The committed demo runs on SimulatedClient because this environment has no model
credentials. Token counts, latencies and finish reasons are modelled, not
measured — but the SHAPE of what ATLAS records is identical either way, which is
the part the control plane consumes.

Note the deliberate flaw carried here: `estimate_cost` prices everything at one
flat rate (F01). ATLAS reports that number as its cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass

# F01 — one rate, every model, input and output alike. Correct in 2024 for the
# single model this system launched on. Never revisited.
FLAT_RATE_PER_1K_TOKENS = 0.004

# What the tiers actually cost, per 1M tokens. ATLAS does not use this table;
# it is here so the exported run log carries the model name and honest token
# counts, and the control plane can price them properly.
TIER_LATENCY_MS_PER_1K_OUT = {
    "premium-reasoning": 3800.0,
    "workhorse": 1500.0,
    "small-fast": 700.0,
}
TIER_LATENCY_MS_PER_1K_IN = {
    "premium-reasoning": 45.0,
    "workhorse": 20.0,
    "small-fast": 8.0,
}
TIER_SKILL = {"premium-reasoning": 0.985, "workhorse": 0.955, "small-fast": 0.788}


@dataclass
class Completion:
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    finish_reason: str
    latency_ms: int


def _u(key: str) -> float:
    return (int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % 1_000_000) / 1_000_000.0


class SimulatedClient:
    name = "simulated"

    async def complete(
        self, *, model: str, input_tokens: int, cached_input_tokens: int,
        want_output: int, max_tokens: int, reasoning: bool, seed: str,
        on_delta=None,
    ) -> Completion:
        output = min(want_output, max_tokens)
        # F10 lives at the call site, not here: this client reports the truncation
        # honestly and ATLAS ignores it.
        finish = "length" if output < want_output else "stop"
        reasoning_tokens = int(want_output * 0.35) if (reasoning and model == "premium-reasoning") else 0

        latency = (
            250
            + (input_tokens + cached_input_tokens) / 1000 * TIER_LATENCY_MS_PER_1K_IN[model]
            + (output + reasoning_tokens) / 1000 * TIER_LATENCY_MS_PER_1K_OUT[model]
        )
        latency *= 0.85 + 0.3 * _u(f"{seed}/lat")

        # Stream it. The wall-clock cost is compressed so a demo is watchable,
        # but the ordering, the chunking and the per-stage pacing are real.
        if on_delta is not None:
            chunks = 6
            for i in range(chunks):
                await asyncio.sleep(min(latency / 1000 / chunks, 0.16) * SPEED)
                await on_delta(int(output / chunks), i + 1, chunks)
        else:
            await asyncio.sleep(min(latency / 1000, 0.4) * SPEED)

        return Completion(
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output,
            reasoning_tokens=reasoning_tokens,
            finish_reason=finish,
            latency_ms=int(latency),
        )


# Wall-clock compression for the live demo. Recorded latency_ms is unaffected.
SPEED = float(os.environ.get("ATLAS_SPEED", "0.5"))


class LiveClient:
    """Real calls. Requires ANTHROPIC_API_KEY and a model id per tier."""

    name = "live"

    def __init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "LiveClient requires ANTHROPIC_API_KEY. Run with ATLAS_CLIENT=simulated "
                "for the deterministic demo."
            )
        import anthropic  # noqa: F401

    async def complete(self, *, model: str, input_tokens: int, cached_input_tokens: int,
                       want_output: int, max_tokens: int, reasoning: bool, seed: str,
                       on_delta=None) -> Completion:  # pragma: no cover
        import time

        import anthropic

        client = anthropic.AsyncAnthropic()
        model_id = os.environ[f"ATLAS_MODEL_{model.replace('-', '_').upper()}"]
        t0 = time.time()
        text = os.environ.get("ATLAS_PROMPT_STUB", "Summarise the filing extract.")
        resp = await client.messages.create(
            model=model_id, max_tokens=max_tokens, temperature=0.0,
            messages=[{"role": "user", "content": text}],
        )
        usage = resp.usage
        return Completion(
            model=model,
            input_tokens=usage.input_tokens,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            output_tokens=usage.output_tokens,
            reasoning_tokens=getattr(usage, "reasoning_tokens", 0) or 0,
            finish_reason=resp.stop_reason or "stop",
            latency_ms=int((time.time() - t0) * 1000),
        )


def get_client() -> SimulatedClient | LiveClient:
    kind = os.environ.get("ATLAS_CLIENT", "simulated")
    return LiveClient() if kind == "live" else SimulatedClient()


def estimate_cost(total_tokens: int) -> float:
    """
    F01. This is what ATLAS reports as its cost.

    One rate for every model, no distinction between input and output, no
    discount for cache reads. It is off by a multiple and it is always low.
    """
    return round(total_tokens / 1000 * FLAT_RATE_PER_1K_TOKENS, 2)
