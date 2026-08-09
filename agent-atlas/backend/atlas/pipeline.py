"""
ATLAS — Analyst Toolkit for Long-form Automated Screening.

A seven-stage equity-research agent that produces an issuer risk memo:

    resolve_entity -> fetch_filings -> extract_financials -> peer_comparison
                   -> risk_scoring -> compliance_check -> draft_memo

This is written the way these systems are actually written. The flaws in
flaws.py are implemented here for real, not simulated:

  F04  `_call_with_retry` retries inside the stage and returns only the final
       result. The caller cannot see that it happened.
  F05  `_filing_context` rebuilds the same preamble for every stage and marks it
       all fresh. Nothing enables prompt caching.
  F06  `_peer_pass` recurses into each peer's peers with no visited set and no
       depth limit, re-sending the accumulated transcript each hop.
  F10  `draft_memo` sets max_tokens and never reads finish_reason.
  F03  the run is COMPLETE if nothing raised.

One concession to running this on a laptop: `_peer_pass` has a hard span budget
so the demo cannot wedge the process. In production the equivalent stop was the
provider's rate limiter, several hundred dollars later. The event stream says so
when it fires.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from atlas.model_client import TIER_SKILL, Completion, estimate_cost, get_client
from atlas.universe import ANALYSTS, DESKS, MANDATES, TOKENS_PER_PAGE, Issuer, issuer

SYSTEM_PROMPT_TOKENS = 2_400
RISK_RUBRIC_TOKENS = 3_100
COMPLIANCE_CHECKLIST_TOKENS = 1_900
MEMO_TEMPLATE_TOKENS = 1_400

# The safety valve described above. Not a design feature.
HARD_SPAN_BUDGET = 34

# Real context windows are finite, so a real runaway does not grow without
# bound — it pins itself at the window and pays the maximum on every hop. ATLAS
# truncates the transcript to fit and keeps going, which is why the loop never
# raises anything for anyone to notice.
CONTEXT_WINDOW_TOKENS = 180_000


@dataclass
class Profile:
    id: str
    label: str
    note: str
    model_by_stage: dict[str, str]
    filing_extract_pages: int
    max_peers: int
    peer_depth_limit: int | None
    memo_max_tokens: int
    reasoning: bool


PROFILES: dict[str, Profile] = {
    "standard": Profile(
        id="standard",
        label="STANDARD",
        note="The configuration that has been in production since launch.",
        model_by_stage={
            "resolve_entity": "small-fast",
            "extract_financials": "workhorse",
            "peer_comparison": "workhorse",
            "risk_scoring": "premium-reasoning",
            "compliance_check": "workhorse",
            "draft_memo": "workhorse",
        },
        filing_extract_pages=64,
        max_peers=3,
        peer_depth_limit=None,   # F06
        memo_max_tokens=4_000,
        reasoning=True,
    ),
    # F07 — the change that was shipped on a Friday because spend was over budget.
    # Cheaper on every axis. Nothing evaluated it.
    "cost_optimized": Profile(
        id="cost_optimized",
        label="COST-OPTIMIZED",
        note="Shipped 2026-08-03 to bring spend under the monthly cap. No evaluation was run.",
        model_by_stage={
            "resolve_entity": "small-fast",
            "extract_financials": "workhorse",
            "peer_comparison": "small-fast",
            "risk_scoring": "small-fast",
            "compliance_check": "small-fast",
            "draft_memo": "small-fast",
        },
        filing_extract_pages=24,
        max_peers=2,
        peer_depth_limit=None,
        memo_max_tokens=1_200,
        reasoning=False,
    ),
}


@dataclass
class RunContext:
    run_id: str
    ticker: str
    profile: Profile
    desk: str
    mandate: str
    analyst: str
    started_at: str
    spans: list[dict[str, Any]] = field(default_factory=list)
    transcript_tokens: int = 0
    peer_calls: int = 0
    hard_stopped: bool = False
    silent_retries: int = 0


def _u(key: str) -> float:
    return (int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % 1_000_000) / 1_000_000.0


def _assign(key: str, options: tuple[str, ...]) -> str:
    return options[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)]


def _fingerprint(stage: str, model: str, subject: str) -> str:
    return hashlib.sha1(f"{stage}|{model}|{subject}".encode()).hexdigest()[:16]


class AtlasRun:
    def __init__(self, ticker: str, profile_id: str = "standard") -> None:
        if profile_id not in PROFILES:
            raise KeyError(f"unknown profile '{profile_id}'")
        self.issuer: Issuer = issuer(ticker)
        self.profile = PROFILES[profile_id]
        self.client = get_client()
        run_id = f"ATL-{uuid.uuid4().hex[:10].upper()}"
        seed = f"{self.issuer.ticker}/{profile_id}"
        self.ctx = RunContext(
            run_id=run_id,
            ticker=self.issuer.ticker,
            profile=self.profile,
            desk=_assign(seed + "desk", DESKS),
            mandate=_assign(seed + "mandate", MANDATES),
            analyst=_assign(seed + "analyst", ANALYSTS),
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._t0 = time.time()
        self._emit: Callable | None = None

    # --- the flaws, implemented -------------------------------------------
    def _filing_context(self) -> int:
        """
        F05. Every stage rebuilds the same filing preamble and sends it fresh.

        There is no caching flag anywhere in this function, and each stage calls
        it independently, which is exactly why nobody noticed.
        """
        pages = min(self.profile.filing_extract_pages, self.issuer.filing_pages)
        return pages * TOKENS_PER_PAGE + SYSTEM_PROMPT_TOKENS

    async def _call_with_retry(
        self, *, stage: str, model: str, input_tokens: int, want_output: int,
        max_tokens: int, reasoning: bool, subject: str, depth: int = 1,
        stream: bool = True,
    ) -> Completion:
        """
        F04. Retries structured-output failures locally and returns only the
        winner. Every retry is a real API call that really costs money, and the
        function's return type has nowhere to say so.

        The spans are appended to the debug trace — engineering needed them for
        debugging — but nothing above this line reads them, and nothing joins
        them to a cost.
        """
        attempts = 0
        p_fail = {"small-fast": 0.22, "workhorse": 0.07, "premium-reasoning": 0.03}[model]
        p_fail += 0.14 * self.issuer.complexity

        while True:
            seed = f"{self.ctx.run_id}/{stage}/{subject}/{attempts}"
            on_delta = None
            if stream and self._emit:
                async def on_delta(n: int, i: int, total: int, _stage=stage):
                    await self._emit("delta", {"stage": _stage, "tokens": n,
                                               "chunk": i, "chunks": total})

            completion = await self.client.complete(
                model=model, input_tokens=input_tokens, cached_input_tokens=0,
                want_output=want_output, max_tokens=max_tokens, reasoning=reasoning,
                seed=seed, on_delta=on_delta,
            )
            self._record(stage, completion, retry_index=attempts, depth=depth, subject=subject)

            failed = attempts < 3 and _u(seed + "/parse") < p_fail
            if not failed:
                return completion
            attempts += 1
            self.ctx.silent_retries += 1
            # Not emitted to the caller. Logged at DEBUG, which nobody has on.
            if self._emit:
                await self._emit("debug_retry", {
                    "stage": stage, "attempt": attempts,
                    "note": "structured output failed to parse; retrying (DEBUG level)",
                })

    def _record(self, stage: str, c: Completion, *, retry_index: int, depth: int,
                subject: str) -> None:
        self.ctx.spans.append({
            "span_id": f"{self.ctx.run_id}-{len(self.ctx.spans):03d}",
            "stage": stage,
            "model": c.model,
            "input_tokens": c.input_tokens,
            "cached_input_tokens": c.cached_input_tokens,
            "output_tokens": c.output_tokens,
            "reasoning_tokens": c.reasoning_tokens,
            "finish_reason": c.finish_reason,
            "latency_ms": c.latency_ms,
            "retry_index": retry_index,
            "depth": depth,
            "subject": subject,
            "fingerprint": _fingerprint(stage, c.model, subject),
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        })

    async def _peer_pass(self, ticker: str, depth: int) -> None:
        """
        F06. Expand each peer's peers to enrich the comparison.

        No visited set. No depth limit on the standard profile. The accumulated
        transcript is re-sent on every hop, so context — and therefore cost —
        grows with the square of the walk.

        On sparse sectors this terminates in two hops and looks fine. That is why
        it is still here.
        """
        peer_list = issuer(ticker).peers[: self.profile.max_peers]
        for peer in peer_list:
            if self.ctx.peer_calls >= HARD_SPAN_BUDGET:
                if not self.ctx.hard_stopped:
                    self.ctx.hard_stopped = True
                    await self._emit("hard_stop", {
                        "note": "span budget exhausted — process killed by operator. "
                                "In production the stop was the provider rate limit.",
                        "peer_calls": self.ctx.peer_calls,
                    })
                return

            self.ctx.peer_calls += 1
            self.ctx.transcript_tokens += 3_200 + int(1_800 * depth)
            await self._emit("tool_call", {
                "stage": "peer_comparison", "tool": "peer_lookup",
                "target": peer, "depth": depth, "call": self.ctx.peer_calls,
            })
            await self._call_with_retry(
                stage="peer_comparison",
                model=self.profile.model_by_stage["peer_comparison"],
                # The transcript is re-sent whole. This is the growth term.
                input_tokens=min(
                    CONTEXT_WINDOW_TOKENS,
                    self._filing_context() // 2 + self.ctx.transcript_tokens,
                ),
                want_output=900 + 60 * depth,
                max_tokens=2_000, reasoning=False,
                subject=peer, depth=depth, stream=False,
            )
            limit = self.profile.peer_depth_limit
            if limit is None or depth < limit:
                await self._peer_pass(peer, depth + 1)

    # --- the pipeline ------------------------------------------------------
    async def stream(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        queue: list[tuple[str, dict[str, Any]]] = []

        async def emit(kind: str, payload: dict[str, Any]) -> None:
            queue.append((kind, payload))

        self._emit = emit
        gen = self._execute()

        async for _ in gen:
            while queue:
                yield queue.pop(0)
        while queue:
            yield queue.pop(0)

    async def _execute(self) -> AsyncIterator[None]:
        iss = self.issuer
        p = self.profile
        await self._emit("run_start", {
            "run_id": self.ctx.run_id, "ticker": iss.ticker, "issuer": iss.name,
            "sector": iss.sector, "profile": p.label, "profile_note": p.note,
            "desk": self.ctx.desk, "mandate": self.ctx.mandate, "analyst": self.ctx.analyst,
            "filing_pages": iss.filing_pages, "extract_pages": p.filing_extract_pages,
        })
        yield

        # 1 — resolve_entity
        await self._emit("stage_start", {"stage": "resolve_entity", "n": 1})
        yield
        await self._call_with_retry(
            stage="resolve_entity", model=p.model_by_stage["resolve_entity"],
            input_tokens=1_100, want_output=180, max_tokens=512, reasoning=False,
            subject=iss.ticker,
        )
        await self._emit("stage_end", {"stage": "resolve_entity",
                                       "detail": f"{iss.ticker} → {iss.name} ({iss.sector})"})
        yield

        # 2 — fetch_filings (retrieval; no completion call, but real spend)
        await self._emit("stage_start", {"stage": "fetch_filings", "n": 2})
        yield
        pages = min(p.filing_extract_pages, iss.filing_pages)
        self._record("fetch_filings", Completion(
            model="small-fast", input_tokens=pages * TOKENS_PER_PAGE, cached_input_tokens=0,
            output_tokens=0, reasoning_tokens=0, finish_reason="stop", latency_ms=900,
        ), retry_index=0, depth=1, subject="10-K")
        await self._emit("stage_end", {
            "stage": "fetch_filings",
            "detail": f"{pages} of {iss.filing_pages} pages extracted "
                      f"({pages * TOKENS_PER_PAGE:,} tokens)",
        })
        yield

        # 3 — extract_financials
        await self._emit("stage_start", {"stage": "extract_financials", "n": 3})
        yield
        await self._call_with_retry(
            stage="extract_financials", model=p.model_by_stage["extract_financials"],
            input_tokens=self._filing_context(), want_output=iss.figures * 42,
            max_tokens=8_000, reasoning=False, subject="financials",
        )
        # The extract targets MD&A, risk factors and the notes — the ~16% of a filing
        # that carries the tagged figures. Cutting the extract cuts straight into it.
        coverage = min(1.0, pages / max(1, iss.filing_pages * 0.16))
        skill = TIER_SKILL[p.model_by_stage["extract_financials"]]
        figures_found = int(round(iss.figures * coverage * skill * (1 - 0.12 * iss.complexity)))
        await self._emit("stage_end", {
            "stage": "extract_financials",
            "detail": f"{figures_found} tagged figures extracted",
        })
        yield

        # 4 — peer_comparison  (F06 lives here)
        await self._emit("stage_start", {"stage": "peer_comparison", "n": 4})
        yield
        await self._peer_pass(iss.ticker, depth=1)
        await self._emit("stage_end", {
            "stage": "peer_comparison",
            "detail": f"{self.ctx.peer_calls} peer lookups"
                      + (" — HARD STOPPED" if self.ctx.hard_stopped else ""),
        })
        yield

        # 5 — risk_scoring
        await self._emit("stage_start", {"stage": "risk_scoring", "n": 5})
        yield
        await self._call_with_retry(
            stage="risk_scoring", model=p.model_by_stage["risk_scoring"],
            input_tokens=self._filing_context() + RISK_RUBRIC_TOKENS + self.ctx.transcript_tokens // 3,
            want_output=iss.figures * 16 + 600, max_tokens=6_000, reasoning=p.reasoning,
            subject="risk",
        )
        await self._emit("stage_end", {"stage": "risk_scoring", "detail": "risk factors scored"})
        yield

        # 6 — compliance_check
        await self._emit("stage_start", {"stage": "compliance_check", "n": 6})
        yield
        await self._call_with_retry(
            stage="compliance_check", model=p.model_by_stage["compliance_check"],
            input_tokens=self._filing_context() + COMPLIANCE_CHECKLIST_TOKENS,
            want_output=iss.disclosures * 55 + 300, max_tokens=4_000, reasoning=False,
            subject="compliance",
        )
        comp_skill = TIER_SKILL[p.model_by_stage["compliance_check"]]
        disclosures_flagged = int(round(
            iss.disclosures * comp_skill * coverage * (1 - 0.18 * iss.complexity)))
        await self._emit("stage_end", {
            "stage": "compliance_check",
            "detail": f"{disclosures_flagged} of {iss.disclosures} disclosure items flagged",
        })
        yield

        # 7 — draft_memo  (F10 lives here)
        await self._emit("stage_start", {"stage": "draft_memo", "n": 7})
        yield
        want = 900 + 26 * iss.figures
        memo = await self._call_with_retry(
            stage="draft_memo", model=p.model_by_stage["draft_memo"],
            input_tokens=self._filing_context() + MEMO_TEMPLATE_TOKENS,
            want_output=want, max_tokens=p.memo_max_tokens, reasoning=False,
            subject="memo",
        )
        # F10 — finish_reason is right there in `memo`. It is not read.
        truncated = memo.finish_reason == "length"
        await self._emit("stage_end", {
            "stage": "draft_memo", "detail": f"memo drafted ({memo.output_tokens:,} tokens)",
        })
        yield

        # --- what ATLAS calls done (F03)
        total_tokens = sum(
            s["input_tokens"] + s["cached_input_tokens"] + s["output_tokens"] + s["reasoning_tokens"]
            for s in self.ctx.spans
        )
        elapsed = time.time() - self._t0
        citations_checked = max(6, int(iss.figures * 0.35))
        citations_correct = int(round(citations_checked * min(
            1.0, TIER_SKILL[p.model_by_stage["risk_scoring"]] * (0.90 + 0.10 * coverage))))

        # Analyst review happens in another system (F11). ATLAS never sees this
        # number; the exported debug record carries it only because the desk's
        # timesheet export happens to land in the same data lake.
        missed_figures = iss.figures - figures_found
        missed_disclosures = iss.disclosures - disclosures_flagged
        rework_minutes = round((
            4.0
            + 0.9 * missed_figures
            + 3.4 * missed_disclosures
            + (26.0 if truncated else 0.0)
            + 1.5 * (citations_checked - citations_correct)
        ) * (0.85 + 0.3 * _u(self.ctx.run_id + "/rework")), 1)

        record = {
            "run_id": self.ctx.run_id,
            "ticker": iss.ticker,
            "issuer": iss.name,
            "sector": iss.sector,
            "profile": p.id,
            "profile_label": p.label,
            "desk": self.ctx.desk,
            "mandate": self.ctx.mandate,
            "analyst": self.ctx.analyst,
            "started_at": self.ctx.started_at,
            "elapsed_s": round(elapsed, 2),
            "status": "COMPLETE",           # F03 — nothing raised, therefore fine
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimate_cost(total_tokens),   # F01
            "spans": self.ctx.spans,
            "silent_retries": self.ctx.silent_retries,
            "peer_calls": self.ctx.peer_calls,
            "hard_stopped": self.ctx.hard_stopped,
            # The evidence. ATLAS produces all of it and joins none of it.
            "artifacts": {
                "gold_figures": iss.figures,
                "figures_extracted": figures_found,
                "gold_disclosures": iss.disclosures,
                "disclosures_flagged": disclosures_flagged,
                "citations_checked": citations_checked,
                "citations_correct": citations_correct,
                "memo_truncated": truncated,
                "memo_finish_reason": memo.finish_reason,
                "analyst_rework_minutes": rework_minutes,
            },
        }
        self.record = record
        await self._emit("run_end", {
            # Exactly what the ATLAS UI shows. Four numbers and a tick.
            "run_id": self.ctx.run_id,
            "status": "COMPLETE",
            "elapsed_s": round(elapsed, 2),
            "total_tokens": total_tokens,
            "estimated_cost_usd": record["estimated_cost_usd"],
            "llm_calls": len(self.ctx.spans),
        })
        yield
