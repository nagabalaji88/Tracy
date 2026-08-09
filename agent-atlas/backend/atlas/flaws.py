"""
THE FLAW REGISTRY.

ATLAS is a deliberately realistic production agent, which means it is a
deliberately flawed one. Every flaw below is a pattern that ships in real
internal LLM systems, for real reasons — usually "we needed it live by Q3" or
"the cost report was a nice-to-have".

Nothing here is a strawman. Each entry states what ATLAS does, why a competent
team would have done that, what it costs, and which part of the control plane
notices. The registry is served over the API and rendered in both applications,
so the demo narrative is data rather than slideware.

ATLAS itself does not import this file to change its behaviour. It is
documentation of behaviour that is implemented for real in pipeline.py.
"""

from __future__ import annotations

from typing import Any

FLAWS: list[dict[str, Any]] = [
    {
        "id": "F01",
        "title": "Cost is estimated from one flat token rate",
        "severity": "high",
        "atlas_does": (
            "Multiplies total tokens by a single hardcoded $0.004/1k constant, "
            "regardless of model, regardless of input vs output, regardless of "
            "whether the tokens were cache reads."
        ),
        "why_realistic": (
            "The constant was right when the system launched on one model. Then the "
            "premium tier was introduced for risk scoring and nobody updated it."
        ),
        "consequence": (
            "Measured against per-model pricing over 128 recorded runs, the flat rate is off "
            "by between -54% and +372% per run, and by +1.1% in the monthly total. The errors "
            "offset, so the number that gets reviewed looks right while every number anyone "
            "could act on — per run, per desk, per profile — is wrong."
        ),
        "detected_by": "Module 2 — CostMeter prices every span per model, per token class",
        "control_plane_screen": "Cost explorer",
    },
    {
        "id": "F02",
        "title": "No attribution below the run",
        "severity": "high",
        "atlas_does": "Logs one total per run. No per-stage, per-desk, per-client, per-model split.",
        "why_realistic": (
            "The logger was written for debugging, not for finance. Attribution was "
            "going to be added 'once we see whether anyone uses it'."
        ),
        "consequence": (
            "Nobody can answer which stage, which desk or which mandate is driving spend, "
            "so nobody can act on it."
        ),
        "detected_by": "Module 2 — rollups by team, stage, model and prompt version",
        "control_plane_screen": "Cost explorer",
    },
    {
        "id": "F03",
        "title": "Success means the process did not crash",
        "severity": "critical",
        "atlas_does": (
            "Marks a run COMPLETE if no exception was raised. A memo missing half the "
            "risk factors is COMPLETE. A truncated memo is COMPLETE."
        ),
        "why_realistic": (
            "It is the only success signal available without a human in the loop, and "
            "wiring the human in was a separate project that was descoped."
        ),
        "consequence": (
            "Cost per successful outcome cannot be computed at all, so every cost "
            "decision is made on cost per call."
        ),
        "detected_by": "Module 1 — outcomes carry quality scores and a real success verdict",
        "control_plane_screen": "Promotion board",
    },
    {
        "id": "F04",
        "title": "Retries are swallowed inside the stage",
        "severity": "medium",
        "atlas_does": (
            "Retries structured-output failures up to 3 times in a local loop. The "
            "retries burn tokens and never appear in the log."
        ),
        "why_realistic": "A retry decorator is the correct fix for flaky JSON. Instrumenting it was not in the ticket.",
        "consequence": "A material and growing slice of spend is invisible, and quietly worsens as prompts drift.",
        "detected_by": "Module 2 — retry spans are their own cost bucket",
        "control_plane_screen": "Cost explorer",
    },
    {
        "id": "F05",
        "title": "The filing preamble is re-sent fresh on every stage",
        "severity": "high",
        "atlas_does": (
            "Each stage builds its prompt from scratch, including the same 40k-token "
            "filing extract. Prompt caching is never enabled."
        ),
        "why_realistic": "Each stage was written by a different person, and the prompts are independent by design.",
        "consequence": "The largest single line of spend, paid five times per run at the fresh input rate.",
        "detected_by": "Module 2 cached-vs-fresh split; Module 4 prices the caching lever",
        "control_plane_screen": "Cost explorer / Simulator",
    },
    {
        "id": "F06",
        "title": "Peer comparison recurses without a depth cap or a visited set",
        "severity": "critical",
        "atlas_does": (
            "Expands each peer's own peers to enrich the comparison. The peer graph has "
            "cycles. There is no depth limit, no visited set, and the accumulated "
            "transcript is re-sent on every hop."
        ),
        "why_realistic": (
            "It terminates fine on the sparse-sector issuers it was tested on. Dense "
            "financials-sector graphs were not in the test set."
        ),
        "consequence": "A single request can burn hundreds of dollars in under two minutes.",
        "detected_by": "Module 5 — loop detection, depth limit, per-trace cap, velocity",
        "control_plane_screen": "Circuit breakers",
    },
    {
        "id": "F07",
        "title": "Config changes ship straight to production",
        "severity": "critical",
        "atlas_does": (
            "The COST_OPTIMIZED profile downgrades three stages, halves the peer set and "
            "cuts the output cap. It is a one-line switch with no evaluation behind it."
        ),
        "why_realistic": (
            "Spend was over budget, the change is obviously cheaper, and there was no "
            "harness that could have said otherwise."
        ),
        "consequence": "A large, real, measurable saving is banked — along with a quality regression nobody measures.",
        "detected_by": "Module 1 — paired evaluation and a promotion decision against declared floors",
        "control_plane_screen": "Promotion board",
    },
    {
        "id": "F08",
        "title": "The only budget control is a monthly total",
        "severity": "high",
        "atlas_does": "Compares month-to-date spend against a constant, in a report generated overnight.",
        "why_realistic": "It is what the cloud cost tooling next to it does, and it was consistent with that.",
        "consequence": (
            "A level control on a quantity that moves in seconds. The month's budget can be "
            "gone before the report that would have flagged it runs."
        ),
        "detected_by": "Module 3 degradation ladder; Module 5 spend-velocity breaker",
        "control_plane_screen": "Forecast & budget / Circuit breakers",
    },
    {
        "id": "F09",
        "title": "No latency ceiling",
        "severity": "medium",
        "atlas_does": "Runs to completion however long it takes. p95 is not measured, let alone bounded.",
        "why_realistic": "The workflow is asynchronous, so latency felt like somebody else's metric.",
        "consequence": "Optimisations that trade latency for cost are unbounded, and analysts abandon slow runs.",
        "detected_by": "Module 1 latency ceiling; Module 4 pre-flight",
        "control_plane_screen": "Promotion board / Simulator",
    },
    {
        "id": "F10",
        "title": "The memo is truncated silently",
        "severity": "critical",
        "atlas_does": (
            "Sets max_tokens on the drafting call and ignores the finish_reason that comes "
            "back. A memo cut off mid-sentence is written to the output store as COMPLETE."
        ),
        "why_realistic": "The cap exists precisely to control cost, and finish_reason is easy to not read.",
        "consequence": "The failure mode most likely to reach a client is the one with no signal attached.",
        "detected_by": "Module 1 — truncation_rate is a declared floor with zero tolerance",
        "control_plane_screen": "Promotion board",
    },
    {
        "id": "F11",
        "title": "Analyst rework is recorded in a different system",
        "severity": "high",
        "atlas_does": (
            "Emits the memo and stops. Time spent repairing it is logged against the "
            "analyst's utilisation, in a tool the AI team does not read."
        ),
        "why_realistic": "The two systems have different owners, different budgets and different vendors.",
        "consequence": (
            "The largest real cost of the pipeline sits in a different budget line, so making "
            "the model cheaper and the analyst busier reads as a win."
        ),
        "detected_by": "Module 1/2 — rework minutes are a first-class outcome field, in the numerator",
        "control_plane_screen": "Promotion board / Cost explorer",
    },
    {
        "id": "F12",
        "title": "There is no golden set",
        "severity": "critical",
        "atlas_does": "Has no fixed evaluation corpus. Changes are validated by running one ticket and reading the output.",
        "why_realistic": "Building an annotated corpus of research memos is expensive and unglamorous.",
        "consequence": (
            "No change can be compared to any other change, so every cost decision is an "
            "argument about anecdotes."
        ),
        "detected_by": "Module 1 — paired comparison over a fixed golden set, with a significance test",
        "control_plane_screen": "Promotion board",
    },
]

FLAWS_BY_ID = {f["id"]: f for f in FLAWS}


def summary() -> dict[str, Any]:
    counts: dict[str, int] = {}
    for flaw in FLAWS:
        counts[flaw["severity"]] = counts.get(flaw["severity"], 0) + 1
    return {"total": len(FLAWS), "by_severity": counts, "flaws": FLAWS}
