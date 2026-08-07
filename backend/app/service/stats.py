"""
Small statistics kit. Pure Python, no numpy, no FastAPI.

Used by the promotion engine for paired comparisons and by the forecaster for
Monte Carlo. Everything is seeded so a demo replays identically.
"""

from __future__ import annotations

import math
import random
from typing import Sequence


def mean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("mean of an empty sample; refusing to return 0")
    return sum(xs) / len(xs)


def percentile(xs: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile. p in [0, 100]."""
    if not xs:
        raise ValueError("percentile of an empty sample; refusing to return 0")
    if not 0 <= p <= 100:
        raise ValueError(f"percentile p={p} out of range")
    ordered = sorted(xs)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] * (hi - k) + ordered[hi] * (k - lo)


def paired_bootstrap(
    deltas: Sequence[float],
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> dict[str, float]:
    """
    Bootstrap the mean of paired per-item deltas (candidate - baseline).

    Returns the observed mean plus a percentile confidence interval. If the
    interval straddles zero the difference is not distinguishable from noise on
    this golden set — which is a promotion-blocking fact, not a footnote.
    """
    if not deltas:
        raise ValueError("paired_bootstrap on an empty delta list")
    rng = random.Random(seed)
    n = len(deltas)
    means: list[float] = []
    for _ in range(iterations):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    alpha = (1.0 - confidence) / 2.0
    lo = percentile(means, alpha * 100)
    hi = percentile(means, (1 - alpha) * 100)
    observed = mean(deltas)
    return {
        "observed_mean_delta": round(observed, 8),
        "ci_low": round(lo, 8),
        "ci_high": round(hi, 8),
        "confidence": confidence,
        "iterations": iterations,
        "n_pairs": n,
        "significant": bool(lo > 0 or hi < 0),
    }


def _binom_sf(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Exact; n is small here."""
    total = 0.0
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p**i) * ((1 - p) ** (n - i))
    return total


def sign_test(deltas: Sequence[float]) -> dict[str, float]:
    """
    Two-sided exact sign test on paired deltas. Ties are dropped, which is the
    conservative choice: it shrinks n rather than inventing direction.
    """
    if not deltas:
        raise ValueError("sign_test on an empty delta list")
    pos = sum(1 for d in deltas if d > 0)
    neg = sum(1 for d in deltas if d < 0)
    n = pos + neg
    if n == 0:
        return {"n_effective": 0, "positive": 0, "negative": 0, "p_value": 1.0, "significant": False}
    k = max(pos, neg)
    p_value = min(1.0, 2.0 * _binom_sf(k, n))
    return {
        "n_effective": n,
        "positive": pos,
        "negative": neg,
        "p_value": round(p_value, 6),
        "significant": bool(p_value < 0.05),
    }


def lognormal_fit(xs: Sequence[float]) -> dict[str, float]:
    """Fit mu/sigma of the underlying normal. Positive samples only."""
    positive = [x for x in xs if x > 0]
    if len(positive) < 2:
        raise ValueError("lognormal_fit needs at least 2 positive observations")
    logs = [math.log(x) for x in positive]
    mu = mean(logs)
    var = sum((l - mu) ** 2 for l in logs) / (len(logs) - 1)
    return {"mu": mu, "sigma": math.sqrt(var), "n": len(positive)}
