"""
Seed ATLAS with operating history.

    python -m atlas.batch --mode production --days 21
    python -m atlas.batch --mode golden

`production` is what the desk accumulates on its own: requests arriving across
several weeks, including the financials-sector issuers whose peer graphs send the
agent into a loop.

`golden` runs a FIXED subject list under every profile. ATLAS has no golden set
of its own — that is flaw F12 — so the list is fetched from the control plane's
policy.yaml. The evaluation corpus is part of the contract the control plane
declares, not something the agent brought with it. Falls back to a local default
if the control plane is not running, and says so.

Timestamps are backdated so the history spans real days; latency spacing within a
run is preserved exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import httpx

from atlas import store
from atlas.pipeline import PROFILES, AtlasRun
from atlas.universe import UNIVERSE, tickers

CONTROL_PLANE_URL = "http://127.0.0.1:8000"

# Used only when the control plane cannot be reached. The point of the fallback
# is that the demo still runs, not that ATLAS owns a golden set.
FALLBACK_GOLDEN = ["TSSL", "ORBQ", "VNTA", "KLDR", "PLMR", "GRVN", "ASTR"]


def _u(key: str) -> float:
    return (int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % 1_000_000) / 1_000_000.0


def _backdate(record: dict, started: datetime) -> dict:
    """Shift a run onto a historical clock, preserving inter-span spacing."""
    if not record["spans"]:
        return record
    origin = datetime.fromisoformat(record["spans"][0]["at"])
    record["started_at"] = started.replace(microsecond=0).isoformat()
    for span in record["spans"]:
        delta = datetime.fromisoformat(span["at"]) - origin
        span["at"] = (started + delta).replace(microsecond=0).isoformat()
    return record


async def _run_one(ticker: str, profile: str, started: datetime, environment: str) -> dict:
    run = AtlasRun(ticker, profile)
    async for _ in run.stream():
        pass
    record = _backdate(run.record, started)
    record["environment"] = environment
    store.save(record)
    return record


async def fetch_golden_set() -> tuple[list[str], str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CONTROL_PLANE_URL}/api/v1/ingest/atlas/golden-set")
            resp.raise_for_status()
            body = resp.json()
            return body["subjects"], "control plane policy.yaml"
    except Exception:
        return FALLBACK_GOLDEN, "local fallback (control plane unreachable)"


async def seed_production(days: int) -> int:
    """
    Realistic arrival pattern: weekday-heavy, a handful of issuers per day, with
    the financials cluster showing up at its natural rate rather than being
    singled out. The runaways are found, not planted.
    """
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    universe = tickers()
    made = 0
    for day in range(days):
        stamp = now - timedelta(days=days - 1 - day)
        weekday = stamp.weekday()
        volume = (5 if weekday < 5 else 1) + int(_u(f"vol/{day}") * 4)
        for i in range(volume):
            ticker = universe[int(_u(f"pick/{day}/{i}") * len(universe))]
            # The cost-optimized profile was rolled out part-way through the window.
            profile = "cost_optimized" if day >= days - 5 and _u(f"prof/{day}/{i}") < 0.5 \
                else "standard"
            started = stamp + timedelta(minutes=47 * i)
            record = await _run_one(ticker, profile, started, "production")
            made += 1
            flag = " RUNAWAY" if record["hard_stopped"] else ""
            print(f"  {started:%Y-%m-%d %H:%M}  {ticker:5s} {profile:14s} "
                  f"${record['estimated_cost_usd']:>7.2f}{flag}")
    return made


async def seed_golden() -> int:
    subjects, origin = await fetch_golden_set()
    print(f"golden set from {origin}: {', '.join(subjects)}")
    now = datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
    made = 0
    for profile in PROFILES:
        for i, ticker in enumerate(subjects):
            if ticker not in UNIVERSE:
                print(f"  ! {ticker} is not in the coverage universe — skipped")
                continue
            record = await _run_one(ticker, profile, now + timedelta(minutes=4 * i), "eval")
            made += 1
            a = record["artifacts"]
            print(f"  {profile:14s} {ticker:5s} figures {a['figures_extracted']:>3}/"
                  f"{a['gold_figures']:<3} disclosures {a['disclosures_flagged']:>2}/"
                  f"{a['gold_disclosures']:<2} truncated={str(a['memo_truncated']):5s} "
                  f"rework={a['analyst_rework_minutes']:>6.1f}m")
    return made


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ATLAS run history.")
    parser.add_argument("--mode", choices=["production", "golden", "both"], default="both")
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--clear", action="store_true", help="delete existing runs first")
    args = parser.parse_args()

    if args.clear:
        print(f"cleared {store.clear()} existing runs")
    total = 0
    if args.mode in ("golden", "both"):
        print("== golden-set evaluation ==")
        total += await seed_golden()
    if args.mode in ("production", "both"):
        print(f"== production history, {args.days} days ==")
        total += await seed_production(args.days)
    print(f"\n{total} runs recorded in {store.RUNS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
