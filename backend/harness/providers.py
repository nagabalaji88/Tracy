"""
Run providers — where runs come from.

Two implementations behind one protocol:

  LiveProvider          calls a real model over a real corpus and records real
                        token usage. This is the recording session.
  DeterministicProvider replays a mechanistic model of the pipeline with a fixed
                        seed, so the demo does not depend on the network.

HONESTY BOUNDARY — read this before quoting any number from this repo.
The fixtures committed under backend/fixtures/ were produced by
DeterministicProvider, because this build environment has no model credentials.
They are *recorded runs* in the sense that matters to the control plane — the
measurement core reads only what is in the trace and outcome tables and cannot
tell which provider wrote them — but they are not live API calls. Re-record with
`python -m harness.record_runs --provider live` against a real corpus to replace
them; nothing downstream changes.

What the control plane never does, under either provider, is invent a quality
score. Scores are always computed by a Scorer from recorded artifacts.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any, Protocol

from harness.golden_set import GoldenDoc
from harness.workload import Config

# --- mechanistic constants for DeterministicProvider -------------------------
# Properties of the simulated recording, not of the control plane.
SYSTEM_PROMPT_TOKENS = 1800
RISK_RUBRIC_TOKENS = 2400
MEMO_TEMPLATE_TOKENS = 1200
PAGES_PER_SECTION = 12
PASSAGE_TOKENS = 900
PASSAGE_UTILISATION = 0.20      # retrieved passages overlap the document text
DOC_READ_MULTIPLIER = 1.15      # the document must be read regardless of top-k
CLAUSE_JSON_TOKENS = 55
RISK_OUT_PER_CLAUSE = 18
RISK_OUT_BASE = 300
REASONING_PER_CLAUSE = 22
MEMO_BASE_TOKENS = 700
MEMO_PER_CLAUSE = 18
EVIDENCE_TOKENS_PER_K = 450

CACHE_FRESH_FRACTION = 0.35     # first read is fresh, section repeats are cached
RISK_CACHE_FRACTION = 0.50
SEMANTIC_CACHE_HIT_RATE = 0.35

MS_PER_1K_OUTPUT = {
    "premium-reasoning": 3800.0,
    "workhorse": 1500.0,
    "small-fast": 700.0,
    "embedding-small": 0.0,
}
MS_PER_1K_INPUT = {
    "premium-reasoning": 45.0,
    "workhorse": 20.0,
    "small-fast": 8.0,
    "embedding-small": 3.0,
}
STAGE_OVERHEAD_MS = 400

RETRY_BASE = {"premium-reasoning": 0.02, "workhorse": 0.05, "small-fast": 0.18, "embedding-small": 0.0}

EXTRACT_SKILL = {"premium-reasoning": 0.99, "workhorse": 0.98, "small-fast": 0.80, "embedding-small": 1.0}

# Retrieval coverage saturates in top_k; the scale k0 grows with document length
# and structural weirdness. This is the mechanism by which a context cut becomes
# a recall cut.
K0_BASE = 1.0
K0_STRUCT = 2.4
K0_LOG_PAGES = 0.8

HALLUCINATION_RATE = {"premium-reasoning": 0.004, "workhorse": 0.010, "small-fast": 0.055,
                      "embedding-small": 0.0}

# Recorded human rework, in minutes, from the annotation session.
REWORK_BASE_MIN = 2.5
REWORK_PER_MISSED_CLAUSE = 1.15
REWORK_TRUNCATION_MIN = 21.0
REWORK_PER_HALLUCINATION = 3.2
NO_SYNTHESIS_REWORK_MIN = 18.0
REWORK_PER_BAD_CITATION = 1.6
# Share of retried runs that fail again and are abandoned. The analyst then does
# the whole document by hand.
TERMINAL_FAILURE_SHARE = 0.30
REWORK_TERMINAL_FAILURE_MIN = 42.0
NO_RISK_CITATION_FACTOR = 0.62


class RunProvider(Protocol):
    name: str

    def run(self, doc: GoldenDoc, config: Config, seed_key: str) -> dict[str, Any]:
        """Return {'spans': [...], 'artifacts': {...}} for one document."""
        ...


def _u(key: str) -> float:
    """Deterministic uniform(0,1) from a string key."""
    h = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    return (h % 1_000_000) / 1_000_000.0


def _fingerprint(stage: str, model: str, prompt_version: str, doc_id: str) -> str:
    return hashlib.sha1(f"{stage}|{model}|{prompt_version}|{doc_id}".encode()).hexdigest()[:16]


class DeterministicProvider:
    """A mechanistic model of the pipeline. Seeded, so the demo replays exactly."""

    name = "deterministic/v1"

    def run(self, doc: GoldenDoc, config: Config, seed_key: str) -> dict[str, Any]:
        stages = config.stages()
        n_sections = max(1, math.ceil(doc.pages / PAGES_PER_SECTION))
        spans: list[dict[str, Any]] = []
        finish_reasons: list[str] = []

        # --- retrieval coverage ------------------------------------------------
        if "retrieve" in stages:
            k0 = K0_BASE + K0_STRUCT * doc.structure_penalty + K0_LOG_PAGES * math.log10(max(10, doc.pages))
            coverage = 1.0 - math.exp(-config.top_k / k0)
        else:
            # No retrieval: the whole document is fed in. Perfect coverage, huge input.
            coverage = 1.0

        # --- stage: retrieve ---------------------------------------------------
        if "retrieve" in stages:
            cache_hit = config.semantic_cache and _u(f"{seed_key}/semcache") < SEMANTIC_CACHE_HIT_RATE
            spans.append(self._span(
                stage="retrieve", config=config, doc=doc,
                input_fresh=0 if cache_hit else doc.doc_tokens,
                input_cached=doc.doc_tokens if cache_hit else 0,
                output=0, reasoning=0, finish_reason="stop",
                cost_bucket="embedding", retry_index=0, depth=1,
            ))
            finish_reasons.append("stop")

        # --- stage: clause_extract --------------------------------------------
        extract_model = config.model_by_stage["clause_extract"]
        if "retrieve" in stages:
            ctx = doc.doc_tokens * DOC_READ_MULTIPLIER + (
                config.top_k * PASSAGE_TOKENS * n_sections * PASSAGE_UTILISATION
            )
        else:
            ctx = doc.doc_tokens * 2.1  # re-read per section without retrieval
        extract_input = int(ctx + SYSTEM_PROMPT_TOKENS * n_sections)
        extract_output = int(doc.clause_count * CLAUSE_JSON_TOKENS)
        if config.prompt_cache:
            fresh = int(extract_input * CACHE_FRESH_FRACTION)
            cached = extract_input - fresh
        else:
            fresh, cached = extract_input, 0
        spans.append(self._span(
            stage="clause_extract", config=config, doc=doc,
            input_fresh=fresh, input_cached=cached,
            output=extract_output, reasoning=0, finish_reason="stop",
            cost_bucket="inference", retry_index=0, depth=1,
        ))
        finish_reasons.append("stop")

        # structured-output failure -> retries, charged as retry spend. A fraction
        # of those retries fail again and the run is abandoned: the pipeline spent
        # money and produced nothing, which is the cheapest way to have a very
        # expensive successful outcome.
        p_retry = RETRY_BASE[extract_model] + 0.12 * doc.structure_penalty
        retried = _u(f"{seed_key}/retry") < p_retry
        terminal_failure = retried and _u(f"{seed_key}/retry2") < TERMINAL_FAILURE_SHARE
        n_retries = (2 if terminal_failure else 1) if retried else 0
        for r in range(1, n_retries + 1):
            spans.append(self._span(
                stage="clause_extract", config=config, doc=doc,
                input_fresh=fresh, input_cached=cached,
                output=int(extract_output * 0.6), reasoning=0,
                finish_reason="content_filter" if (terminal_failure and r == n_retries) else "stop",
                cost_bucket="retry", retry_index=r, depth=1,
            ))
        if terminal_failure:
            # The run stops here. Downstream stages never execute.
            return {
                "spans": spans,
                "artifacts": {
                    "gold_clause_ids": list(doc.gold_clause_ids),
                    "predicted_clause_ids": [],
                    "stage_finish_reasons": finish_reasons + ["content_filter"],
                    "citations_checked": max(5, int(doc.clause_count * 0.4)),
                    "citations_correct": 0,
                    "terminal_failure": "structured_output_failure_after_retries",
                    "human_rework_minutes": round(
                        REWORK_TERMINAL_FAILURE_MIN * (0.85 + 0.3 * _u(f"{seed_key}/rework")), 2),
                },
            }

        # --- stage: risk_assess ------------------------------------------------
        risk_model = config.model_by_stage.get("risk_assess")
        risk_output = 0
        if "risk_assess" in stages:
            risk_input = int(
                extract_output + RISK_RUBRIC_TOKENS + config.top_k * EVIDENCE_TOKENS_PER_K
            )
            risk_output = int(doc.clause_count * RISK_OUT_PER_CLAUSE + RISK_OUT_BASE)
            reasoning = int(doc.clause_count * REASONING_PER_CLAUSE) if (
                config.reasoning and risk_model == "premium-reasoning"
            ) else 0
            if config.prompt_cache:
                r_fresh = int(risk_input * RISK_CACHE_FRACTION)
                r_cached = risk_input - r_fresh
            else:
                r_fresh, r_cached = risk_input, 0
            spans.append(self._span(
                stage="risk_assess", config=config, doc=doc,
                input_fresh=r_fresh, input_cached=r_cached,
                output=risk_output, reasoning=reasoning, finish_reason="stop",
                cost_bucket="inference", retry_index=0, depth=2,
            ))
            finish_reasons.append("stop")

        # --- stage: synthesize -------------------------------------------------
        truncated = False
        if "synthesize" in stages:
            memo_wanted = int(MEMO_BASE_TOKENS + MEMO_PER_CLAUSE * doc.clause_count)
            memo_emitted = min(memo_wanted, config.output_cap)
            truncated = memo_emitted < memo_wanted
            syn_input = int((risk_output or extract_output) + MEMO_TEMPLATE_TOKENS)
            spans.append(self._span(
                stage="synthesize", config=config, doc=doc,
                input_fresh=syn_input, input_cached=0,
                output=memo_emitted, reasoning=0,
                finish_reason="length" if truncated else "stop",
                cost_bucket="inference", retry_index=0, depth=3,
                batch="synthesize" in config.batch_stages,
            ))
            finish_reasons.append("length" if truncated else "stop")

        # --- what the pipeline actually returned -------------------------------
        skill = EXTRACT_SKILL[extract_model]
        struct_term = 1.0 - 0.06 * doc.structure_penalty
        recall_target = max(0.0, min(1.0, coverage * skill * struct_term))
        n_found = int(round(recall_target * doc.clause_count))

        # Which clauses were found is a deterministic shuffle, so recall is
        # computed by the Scorer from id sets rather than handed to it.
        ordered = sorted(doc.gold_clause_ids, key=lambda cid: _u(f"{seed_key}/{cid}"))
        predicted = list(ordered[:n_found])
        n_hall = int(round(doc.clause_count * HALLUCINATION_RATE[extract_model] *
                           (1 + doc.structure_penalty)))
        predicted += [f"{doc.doc_id}::X{i:03d}" for i in range(n_hall)]

        checked = max(5, int(doc.clause_count * 0.4))
        cite_skill = EXTRACT_SKILL[risk_model or extract_model]
        correct = int(round(checked * min(1.0, cite_skill * (0.93 + 0.07 * coverage))))
        if "risk_assess" not in stages:
            # Citations are verified against the risk rubric. Drop the stage and
            # nothing checks them.
            correct = int(round(correct * NO_RISK_CITATION_FACTOR))

        missed = doc.clause_count - n_found
        rework = (
            REWORK_BASE_MIN
            + REWORK_PER_MISSED_CLAUSE * missed
            + (REWORK_TRUNCATION_MIN if truncated else 0.0)
            + REWORK_PER_HALLUCINATION * n_hall
            # No synthesis stage means the analyst writes the review memo by hand.
            # The model spend goes down; the cost of the work goes up.
            + (NO_SYNTHESIS_REWORK_MIN if "synthesize" not in stages else 0.0)
            # Every citation that does not hold up has to be chased back to the
            # source document by hand.
            + REWORK_PER_BAD_CITATION * (checked - correct)
        ) * (0.85 + 0.3 * _u(f"{seed_key}/rework"))

        return {
            "spans": spans,
            "artifacts": {
                "gold_clause_ids": list(doc.gold_clause_ids),
                "predicted_clause_ids": predicted,
                "stage_finish_reasons": finish_reasons,
                "citations_checked": checked,
                "citations_correct": correct,
                "human_rework_minutes": round(rework, 2),
            },
        }

    def _span(
        self, *, stage: str, config: Config, doc: GoldenDoc,
        input_fresh: int, input_cached: int, output: int, reasoning: int,
        finish_reason: str, cost_bucket: str, retry_index: int, depth: int,
        batch: bool = False,
    ) -> dict[str, Any]:
        model = config.model_by_stage[stage]
        latency = (
            STAGE_OVERHEAD_MS
            + (input_fresh + input_cached) / 1000.0 * MS_PER_1K_INPUT[model]
            + (output + reasoning) / 1000.0 * MS_PER_1K_OUTPUT[model]
        )
        if batch:
            latency *= 3.0
        return {
            "stage": stage,
            "model": model,
            "gen_ai_system": "anthropic",
            "response_model": model,
            "input_tokens_fresh": int(input_fresh),
            "input_tokens_cached": int(input_cached),
            "output_tokens": int(output),
            "reasoning_tokens": int(reasoning),
            "max_output_tokens": config.output_cap,
            "temperature": 0.0,
            "finish_reason": finish_reason,
            "retry_index": retry_index,
            "agent_depth": depth,
            "call_fingerprint": _fingerprint(stage, model, config.prompt_version, doc.doc_id),
            "batch_api": 1 if batch else 0,
            "cost_bucket": cost_bucket,
            "latency_ms": int(latency),
        }


class LiveProvider:
    """
    Real calls, real usage numbers. Requires ANTHROPIC_API_KEY and a corpus
    directory containing, per document, `<doc_id>.txt` and `<doc_id>.gold.json`
    (the annotated clause ids). Fails loudly rather than degrading to simulation.
    """

    name = "live/v1"

    def __init__(self, corpus_dir: str | None = None) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.corpus_dir = corpus_dir or os.environ.get("CONTRACT_CORPUS_DIR", "")
        if not self.api_key:
            raise RuntimeError(
                "LiveProvider requires ANTHROPIC_API_KEY. Recording sessions need "
                "credentials; the demo does not. Use --provider deterministic to "
                "replay the committed fixtures."
            )
        if not self.corpus_dir or not os.path.isdir(self.corpus_dir):
            raise RuntimeError(
                "LiveProvider requires CONTRACT_CORPUS_DIR pointing at the annotated "
                "corpus. Refusing to record runs against documents with no gold set — "
                "there would be nothing to measure recall against."
            )
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError("pip install anthropic to use the live provider") from exc

    def run(self, doc: GoldenDoc, config: Config, seed_key: str) -> dict[str, Any]:  # pragma: no cover
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        text = open(os.path.join(self.corpus_dir, f"{doc.doc_id}.txt")).read()
        gold = json.load(open(os.path.join(self.corpus_dir, f"{doc.doc_id}.gold.json")))

        spans: list[dict[str, Any]] = []
        predicted: list[str] = []
        finish_reasons: list[str] = []

        for stage in config.stages():
            if stage == "retrieve":
                continue  # retrieval is local; instrument it in your own index
            model_id = os.environ[f"MODEL_{config.model_by_stage[stage].replace('-', '_').upper()}"]
            import time

            t0 = time.time()
            resp = client.messages.create(
                model=model_id,
                max_tokens=config.output_cap,
                temperature=0.0,
                messages=[{"role": "user", "content": _stage_prompt(stage, text, predicted)}],
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = resp.usage
            spans.append({
                "stage": stage,
                "model": config.model_by_stage[stage],
                "gen_ai_system": "anthropic",
                "response_model": resp.model,
                "input_tokens_fresh": usage.input_tokens,
                "input_tokens_cached": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": getattr(usage, "reasoning_tokens", 0) or 0,
                "max_output_tokens": config.output_cap,
                "temperature": 0.0,
                "finish_reason": resp.stop_reason,
                "retry_index": 0,
                "agent_depth": config.stages().index(stage),
                "call_fingerprint": _fingerprint(stage, config.model_by_stage[stage],
                                                 config.prompt_version, doc.doc_id),
                "batch_api": 1 if stage in config.batch_stages else 0,
                "cost_bucket": "inference",
                "latency_ms": latency_ms,
            })
            finish_reasons.append(resp.stop_reason or "stop")
            if stage == "clause_extract":
                predicted = _parse_clause_ids(resp.content[0].text)

        return {
            "spans": spans,
            "artifacts": {
                "gold_clause_ids": gold["clause_ids"],
                "predicted_clause_ids": predicted,
                "stage_finish_reasons": finish_reasons,
                "citations_checked": gold["citations_checked"],
                "citations_correct": gold["citations_correct"],
                # Recorded by the human reviewer during the annotation session.
                "human_rework_minutes": gold["human_rework_minutes"],
            },
        }


def _stage_prompt(stage: str, text: str, predicted: list[str]) -> str:  # pragma: no cover
    if stage == "clause_extract":
        return f"Extract every obligation clause as JSON list of ids.\n\n{text}"
    if stage == "risk_assess":
        return f"Assess risk for these clauses: {predicted}\n\n{text[:20000]}"
    return f"Write the review memo for clauses: {predicted}"


def _parse_clause_ids(raw: str) -> list[str]:  # pragma: no cover
    import json
    import re

    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        raise ValueError("clause_extract returned no parseable JSON list")
    return json.loads(match.group(0))


def get_provider(kind: str) -> RunProvider:
    if kind == "deterministic":
        return DeterministicProvider()
    if kind == "live":
        return LiveProvider()
    raise ValueError(f"unknown provider '{kind}' (expected: deterministic | live)")
