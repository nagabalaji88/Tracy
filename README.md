# AI Cost-Quality Control Plane

> `minimize cost  subject to  quality >= floor  AND  latency <= ceiling`

Existing tools measure cost **or** quality. The FinOps Foundation says the metric
that matters is **cost per successful outcome**, not cost per token — and no
shipping product computes it, because computing it requires both numbers in one
place, joined on the business outcome the spend contributed to.

This is that join, plus the one behaviour that makes it a control plane rather
than a dashboard: **it rejects a cost saving when measured quality falls below a
declared floor.**

---

## The one screen

Open **Promotion board**. Three configurations, evaluated over the same 24 golden
documents:

| Configuration | Cost / document | Clause recall | Cost / successful outcome | Decision |
|---|---:|---:|---:|---|
| Baseline | $0.716 | 0.951 | $15.88 | — |
| Naive-cheap | $0.289 | **0.611** | **$205.61** | **REJECT** |
| Optimised | $0.417 | 0.950 | $12.40 | PROMOTE |

Three things a judge should be able to read off that table:

1. A **60% cost reduction was measured** — and **rejected**, because clause recall
   came in at 0.611 against a floor of 0.92 that the business declared in
   `policy.yaml`. The saving is real, statistically significant, and refused.
2. Per call, the cheap configuration wins by 60%. Per *successful outcome* — with
   analyst rework in the numerator and only usable results in the denominator —
   it is **13× more expensive**. The ordering inverts.
3. Adding a second use case is a `policy.yaml` entry and two adapter
   implementations. `support_triage` is already wired in that way, with zero
   changes to any service module.

---

## Run it

On Windows, `run-demo.bat` does all of the below in one step — creates the venv,
installs both Python and Node dependency sets, runs the tests, seeds ATLAS, and
starts all four services. Requires Python 3.11+ (3.13 verified) and Node 18+.

```bat
run-demo.bat                 :: everything
run-demo.bat /noatlas        :: control plane only
run-demo.bat /setuponly      :: install, don't start
```

By hand, on any platform:

```bash
# backend  (http://127.0.0.1:8000, docs at /docs)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000

# frontend (http://localhost:5173, proxies /api to the backend)
cd frontend && npm install && npm run dev
```

The store seeds itself from the committed fixtures on first request. Nothing else
is required — no Docker, no Postgres, no API keys.

```bash
# unit tests for the promotion engine (the one place tests are mandatory)
cd backend && PYTHONPATH=. .venv/bin/pytest tests -q

# re-record the runs, and re-calibrate the simulator's lever table
PYTHONPATH=. .venv/bin/python -m harness.record_runs
PYTHONPATH=. .venv/bin/python -m harness.calibrate_levers
```

`POST /api/v1/admin/reset` reloads the store from fixtures and re-reads
`policy.yaml`, so a failed live run cannot kill the demo — and a policy edit can
be demonstrated live.

---

## Where the numbers come from

**Read this before quoting a figure.** The committed fixtures were produced by
`DeterministicProvider`, a seeded mechanistic model of the pipeline, because this
build environment had no model credentials. They are recorded runs in the sense
that matters to the control plane — the measurement core reads only the trace and
outcome tables and cannot tell which provider wrote them — but they are **not
live API calls**. `harness/providers.py` states this at the top of the file, and
`LiveProvider` is implemented alongside: given `ANTHROPIC_API_KEY` and an
annotated corpus, `python -m harness.record_runs --provider live` replaces the
fixtures and nothing downstream changes.

`pricing.yaml` is configuration, not measurement. Verify the rates against your
provider's price list before quoting an absolute dollar figure externally.

What is true under either provider: **no quality score is ever invented.** Scores
are computed by a `Scorer` from recorded artifacts — clause recall is
`|gold ∩ predicted| / |gold|` over recorded id sets — and a metric that was not
measured is absent, never zero. The engine fails loudly rather than defaulting:
a missing model price, an undeclared metric direction, an unmeasured floor, and
an unpaired comparison are all exceptions.

---

## The spine

One record type is the backbone. `GET /api/v1/spine` serves the schema and its
OpenTelemetry GenAI mapping as a public contract.

| | |
|---|---|
| Identity | `trace_id`, `span_id`, `parent_span_id`, `stage` |
| Attribution | `tenant`, `team`, `use_case`, `environment`, `prompt_version`, `config_id` |
| Usage | `input_tokens_fresh`, `input_tokens_cached`, `output_tokens`, `reasoning_tokens` |
| Economics | `retry_index`, `cost_bucket`, `latency_ms`, `cost_usd` |
| The join | **`outcome_id`** — the business outcome this call contributed to |

Fields follow the OTel GenAI conventions where they exist. `outcome_id`,
`cost_bucket`, `prompt_version`, `agent_depth` and `call_fingerprint` are
extensions OTel does not yet define, declared explicitly in `app/schema_def.py`.
The outcome table carries `quality_scores` and `human_rework_minutes` — rework is
first-class because it belongs in the numerator.

---

## Modules

**1 — Measurement core & promotion engine** (`app/service/measurement.py`)
Paired comparison of a candidate against a baseline over the same documents, with
a paired bootstrap and an exact sign test. `promotion_decision` returns
PROMOTE/REJECT with every failing floor and its shortfall. Three rejection codes:
`quality_floor_breach`, `latency_ceiling_breach`, `saving_not_significant` — a
saving whose confidence interval includes zero is refused as noise. 13 unit tests,
no FastAPI or sqlite import.

**2 — Attribution & cost explorer** (`app/service/attribution.py`)
Rollups by team, stage, model and prompt version. The buckets other tools fold
away — retries, cached vs fresh input, CI/eval spend, index regeneration, human
rework — each with an explanation. Rework is **12× model spend**, which is the
entire argument for costing outcomes. Stage economics answers "is Agent 3 worth
what it costs?" from ablation runs and settles it on cost per successful outcome:
two stages pay for themselves, and the retrieval step does not. Heavy tail:
p50/p95/p99 and the top 5% of documents consuming a third of spend.

**3 — Forecast & budget governor** (`app/service/forecast.py`)
Four drivers — volume, tokens per call, retry factor, fan-out — projected
separately and multiplied through a 4,000-iteration Monte Carlo, so p50, p95 and
the tail reserve fall out of the simulation. Fitted on the current prompt regime
only; every deploy is a change point, marked and not smoothed. Deploy-triggered
batch work and incident traces are held out of the driver fit for stated reasons
and still counted in spend. The degradation ladder from `policy.yaml` is evaluated
against actual spend, with the date the p50 path crosses the next rung.

**4 — Optimisation simulator** (`app/service/simulator.py`)
Eight levers whose single-lever effects were **measured**, not guessed
(`harness/calibrate_levers.py` runs the golden set once per lever value with
paired seeds). What stays projected is the composition — and the screen quantifies
that: where a lever selection matches a recorded configuration, the measured
result appears beside the projection with the error between them (0.0%, +7.0%,
+11.8%). Pre-flight blocks a combination that would breach a floor before it runs.

**5 — Circuit breakers** (`app/service/breakers.py`)
A recorded runaway trace replayed span by span. Every breaker is evaluated on
every span, so the screen shows what a later catch would have cost:

```
repeated identical call   span  6    $1.08 spent   $372.72 prevented   ← fired
per-trace spend limit     span 15    $5.08 spent   $368.72 prevented
spend velocity            span 31   $48.29 spent   $325.51 prevented
agent recursion depth     span 33   $72.27 spent   $301.53 prevented
```

The trace burned $373.80 in 78 seconds. A $400 monthly cap goes in under two
minutes at that rate: a monthly cap is a level control, and this needs a
derivative control.

**6 — Executive view** (`app/service/executive.py`)
Cost per successful outcome as the headline, and **savings rejected for quality
reasons** as a first-class line beside savings realised. This system refused
$6,828/yr of savings and banked $4,777 — a tool that only reports savings
realised cannot be trusted about savings at all.

---

## Layout

```
backend/
  policy.yaml            floors, ceilings, budgets, ladder, breakers — the contract
  pricing.yaml           USD per million tokens, by model (configuration)
  app/
    schema_def.py        THE SPINE: trace + outcome schema, OTel mapping
    policy.py            loaders that fail loudly
    adapters/            CostMeter + Scorer protocols, registry, implementations
    repository/          SQL in, plain dicts out
    service/             pure business logic — no FastAPI, no sqlite
    routers/             thin; Pydantic DTOs at the boundary only
  harness/
    golden_set.py        24 documents, oversampled on the hard tail
    workload.py          the 4-stage pipeline and its configurations
    providers.py         LiveProvider | DeterministicProvider
    record_runs.py       the recording session
    calibrate_levers.py  measures the simulator's lever table
  fixtures/              recorded traces, outcomes, configs, lever effects
  tests/                 promotion engine unit tests
frontend/src/pages/      one page per module
```

## Deliberately not built

No auth, no multi-tenancy enforcement (tenant is an attribution dimension, not a
boundary), no live ingestion endpoint, no alerting, no scheduler. The breakers
evaluate and report; they do not terminate a live trace. The simulator cannot
promote a configuration — only a recorded evaluation can, which is the point.
