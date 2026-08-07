"""
THE SPINE.

One record type is the backbone of the whole system: the trace span. Everything
else — attribution, forecasting, promotion, breakers — is a query over it.

Field names follow the OpenTelemetry GenAI semantic conventions wherever a
convention exists. The mapping is declared in OTEL_MAPPING below and is exposed
over the API (`GET /api/v1/spine`) so the schema is part of the public contract,
not an implementation detail.
"""

from __future__ import annotations

# --- OpenTelemetry GenAI semantic-convention mapping -------------------------
# Local column  ->  OTel attribute. Columns absent here are extensions this
# control plane requires and OTel does not yet define (marked in EXTENSIONS).
OTEL_MAPPING: dict[str, str] = {
    "trace_id": "trace.id",
    "span_id": "span.id",
    "parent_span_id": "span.parent_id",
    "stage": "gen_ai.operation.name",
    "gen_ai_system": "gen_ai.system",
    "model": "gen_ai.request.model",
    "response_model": "gen_ai.response.model",
    "input_tokens_fresh": "gen_ai.usage.input_tokens",
    "input_tokens_cached": "gen_ai.usage.cached_input_tokens",
    "output_tokens": "gen_ai.usage.output_tokens",
    "reasoning_tokens": "gen_ai.usage.reasoning_tokens",
    "temperature": "gen_ai.request.temperature",
    "max_output_tokens": "gen_ai.request.max_tokens",
    "finish_reason": "gen_ai.response.finish_reasons",
    "latency_ms": "gen_ai.server.request.duration",
    "started_at": "span.start_time",
    "environment": "deployment.environment.name",
}

# Extensions the cost-quality control plane needs and OTel GenAI does not define.
EXTENSIONS: dict[str, str] = {
    "tenant": "Billing/isolation boundary.",
    "team": "Cost centre the span is charged to.",
    "use_case": "Key into policy.yaml. Determines the floors that apply.",
    "prompt_version": "Every prompt edit is a regime change, not a continuous series.",
    "config_id": "The configuration under evaluation (baseline / candidate).",
    "retry_index": "0 = first attempt. >0 spans are retry spend.",
    "cost_bucket": "inference | retry | eval | embedding | rework | tool.",
    "cost_usd": "Derived by the CostMeter adapter from token counts x pricing.yaml.",
    "outcome_id": "FK to the business outcome this call contributed to.",
    "doc_id": "Unit of work (document / ticket / request).",
    "agent_depth": "Recursion depth. A circuit-breaker input.",
    "call_fingerprint": "Hash of (stage, model, prompt hash). Loop detection input.",
    "batch_api": "Whether the call was submitted through a batch endpoint.",
}

TRACE_COLUMNS: tuple[str, ...] = (
    "span_id",
    "trace_id",
    "parent_span_id",
    "stage",
    "tenant",
    "team",
    "use_case",
    "environment",
    "prompt_version",
    "config_id",
    "doc_id",
    "gen_ai_system",
    "model",
    "response_model",
    "input_tokens_fresh",
    "input_tokens_cached",
    "output_tokens",
    "reasoning_tokens",
    "max_output_tokens",
    "temperature",
    "finish_reason",
    "retry_index",
    "agent_depth",
    "call_fingerprint",
    "batch_api",
    "cost_bucket",
    "latency_ms",
    "cost_usd",
    "outcome_id",
    "started_at",
)

OUTCOME_COLUMNS: tuple[str, ...] = (
    "outcome_id",
    "use_case",
    "config_id",
    "environment",
    "tenant",
    "team",
    "prompt_version",
    "doc_id",
    "doc_tier",
    "succeeded",
    "failure_reason",
    "quality_scores",       # JSON dict, produced by a Scorer adapter
    "human_rework_minutes",  # first-class: it belongs in the numerator
    "timestamp",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    span_id             TEXT PRIMARY KEY,
    trace_id            TEXT NOT NULL,
    parent_span_id      TEXT,
    stage               TEXT NOT NULL,
    tenant              TEXT NOT NULL,
    team                TEXT NOT NULL,
    use_case            TEXT NOT NULL,
    environment         TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    config_id           TEXT NOT NULL,
    doc_id              TEXT,
    gen_ai_system       TEXT NOT NULL,
    model               TEXT NOT NULL,
    response_model      TEXT,
    input_tokens_fresh  INTEGER NOT NULL,
    input_tokens_cached INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    reasoning_tokens    INTEGER NOT NULL,
    max_output_tokens   INTEGER,
    temperature         REAL,
    finish_reason       TEXT,
    retry_index         INTEGER NOT NULL,
    agent_depth         INTEGER NOT NULL,
    call_fingerprint    TEXT,
    batch_api           INTEGER NOT NULL,
    cost_bucket         TEXT NOT NULL,
    latency_ms          INTEGER NOT NULL,
    cost_usd            REAL NOT NULL,
    outcome_id          TEXT,
    started_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_traces_use_case   ON traces(use_case, environment);
CREATE INDEX IF NOT EXISTS ix_traces_config     ON traces(config_id);
CREATE INDEX IF NOT EXISTS ix_traces_outcome    ON traces(outcome_id);
CREATE INDEX IF NOT EXISTS ix_traces_trace      ON traces(trace_id);
CREATE INDEX IF NOT EXISTS ix_traces_started    ON traces(started_at);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id           TEXT PRIMARY KEY,
    use_case             TEXT NOT NULL,
    config_id            TEXT NOT NULL,
    environment          TEXT NOT NULL,
    tenant               TEXT NOT NULL,
    team                 TEXT NOT NULL,
    prompt_version       TEXT NOT NULL,
    doc_id               TEXT NOT NULL,
    doc_tier             TEXT NOT NULL,
    succeeded            INTEGER NOT NULL,
    failure_reason       TEXT,
    quality_scores       TEXT NOT NULL,
    human_rework_minutes REAL NOT NULL,
    timestamp            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_outcomes_config  ON outcomes(use_case, config_id);
CREATE INDEX IF NOT EXISTS ix_outcomes_doc     ON outcomes(doc_id);

-- Registry of the configurations that were recorded. Levers are declarative so
-- Module 4 can project a config that has not been run yet, and Module 1 can put
-- the measured result beside the projection once it has.
CREATE TABLE IF NOT EXISTS configs (
    config_id    TEXT PRIMARY KEY,
    use_case     TEXT NOT NULL,
    label        TEXT NOT NULL,
    role         TEXT NOT NULL,          -- baseline | candidate | ablation
    ablated_stage TEXT,
    levers       TEXT NOT NULL,          -- JSON
    recorded_at  TEXT NOT NULL
);
"""
