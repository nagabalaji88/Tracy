# Demo runbook — a flawed agent, then the control plane on top of it

Two applications. They share no code, no database and no schema.

| | | |
|---|---|---|
| **ATLAS** | `agent-atlas/` | :8100 API, :5174 terminal — a production-shaped research agent with twelve deliberate flaws |
| **Control plane** | `backend/`, `frontend/` | :8000 API, :5173 UI — the cost-quality control plane |

---

## Start everything

```bash
# control plane
cd backend && PYTHONPATH=. uvicorn app.main:app --port 8000 &
cd frontend && npm run dev &                       # :5173

# ATLAS
cd agent-atlas/backend && PYTHONPATH=. uvicorn atlas.server:app --port 8100 &
cd agent-atlas/frontend && npm run dev &            # :5174

# seed ATLAS with 21 days of operating history + golden-set runs
cd agent-atlas/backend
ATLAS_SPEED=0 PYTHONPATH=. python -m atlas.batch --mode both --days 21 --clear
```

---

## Act 1 — watch it fail, on :5174

Pick **NRTH** on the **STANDARD** profile. Press EXECUTE.

The console walks the peer graph: `HRBR → NRTH → HRBR → NRTH`, depth 1 through
18, thirty-four peer lookups, until the process is killed by the operator. Then:

```
✓ COMPLETE
elapsed 12.8s · 8,465,140 tokens · $33.86 · 58 LLM calls
```

Four numbers and a tick. Point at what is missing: no per-stage cost, no
attribution to a desk or a mandate, no quality signal, no record of whether the
memo was usable. COMPLETE means nothing raised.

Open **MONTHLY COST REPORT** — one total against a constant, generated overnight,
with its own list of what it cannot tell you. Open **KNOWN GAPS** — the twelve
flaws, each with why it shipped.

Optionally run **COST-OPTIMIZED** on the same issuer. It is visibly cheaper.
Nothing on this screen can tell you what it cost.

---

## Act 2 — hand it over

Press **↗ SEND RUNS**. ATLAS POSTs its debug records to
`:8000/api/v1/ingest/atlas`. The response says what happened:

```
128 runs → 3,141 spans mapped, 128 outcomes scored
```

Every one of those spans already existed in ATLAS's debug log. Nothing was
instrumented, nothing was rewritten. What was missing was the join: trace →
outcome → policy.

**The cost of onboarding**, as `GET /api/v1/framework` reports it:

- `policy.yaml` — one `use_case` entry, two metric direction declarations
- `app/adapters/atlas.py` — a `Scorer` and a mapping onto the spine
- `app/routers/ingest.py` — one POST route
- **core files changed: 0**

The `CostMeter` was reused unchanged. That reuse alone corrects flaw F01.

---

## Act 3 — the control plane, on :5173

Every screen takes `?use_case=equity_research_memo`.

### Promotion board — F03, F07, F10, F12

| | Cost / memo | Figure accuracy | Disclosure recall | Truncation | Usable | Cost / successful outcome |
|---|---:|---:|---:|---:|---:|---:|
| ATLAS standard | $1.543 | 0.918 | 0.909 | 0.00 | 7/7 | $25.72 |
| ATLAS cost-optimized | $0.229 | **0.778** | **0.620** | **1.00** | **0/7** | **undefined** |

> **REJECTED — figure_accuracy 0.7779 < floor 0.88 (cost −85%)**

An 85% saving, real and statistically significant, refused. All three declared
floors breached. And its cost per successful outcome is not a large number — it
is *undefined*, because across seven golden subjects it produced nothing an
analyst could send.

That is the flaw ATLAS could not have caught: it has no golden set (F12), no
outcome record (F03), and no floor to check against (F07).

### Cost explorer — F01, F02, F04, F05

- **F02**: spend splits by desk (`equity-research` $684, `credit-risk` $441,
  `ib-coverage` $398), by stage, by model. `peer_comparison` alone is **66% of
  all model spend** — the loop is not a corner case, it *is* the cost of the
  system.
- **F04**: retries are their own bucket — **$248, 16% of model spend**,
  completely invisible in ATLAS's own reporting.
- **F05**: cache hit rate 0.0%. The filing preamble is paid fresh, five times a
  run, by construction.
- **F01**: re-pricing the same recorded tokens per model gives **−54% to +372%
  error per run**, and **+1.1% on the monthly total**. The errors offset. The
  number that gets reviewed looks right while every number anyone could act on is
  wrong — which is worse than being wrong in one direction.

### Circuit breakers — F06, F08

Replays ATLAS's worst real trace. All four breakers are evaluated on every span:

```
repeated identical call   span  9    $1.08 spent   $44.64 prevented   ← fired
agent recursion depth     span 11    $1.54 spent   $44.17 prevented
per-trace spend limit     span 25    $8.14 spent   $37.58 prevented
spend velocity            span 55   $31.56 spent   $14.16 prevented
```

The loop detector caught it by structure in nine calls and 4.4 seconds. The trace
burned $45.72 at **$133/min** — ATLAS's $3,000 monthly cap goes in 22 minutes at
that rate, and the report that would have flagged it runs at 02:00 (F08).

### Forecast & governor — F08

Drivers projected separately, p50/p95, tail reserve, ladder evaluated against
actual spend. The honest finding here is that **ongoing work is fine** — 24% of
budget — and **51 incident traces account for $1,431 of $1,523 total model
spend**. The budget is not the problem. The loop is. A monthly cap would never
have told you that.

### Executive view — F11

Cost per successful outcome **$207.69** against cost per call **$0.50**. Success
rate 45.6%. Rework **97.7 analyst hours / $9,277** — six times the model spend,
sitting in a different budget line, in a system the AI team does not read (F11).

### Simulator — the fail-loudly path

`/api/v1/simulate/levers?use_case=equity_research_memo` returns **400**:

> the lever table was calibrated against 'baseline_v1', not 'atlas_standard'.
> Run `python -m harness.calibrate_levers` against this workload before
> simulating it — the simulator will not reuse another workload's multipliers.

Worth showing deliberately. The projection would have rendered happily using
another agent's measured multipliers; refusing is the correct behaviour, and it
is the same rule that makes the rest of the numbers trustworthy.

Stage economics says `not_measured` for every ATLAS stage, for the same reason —
no ablation runs were recorded, so there is no verdict to give.

---

## The three claims, on an agent the control plane did not build

1. **A measured cost reduction was rejected** — 85% cheaper, refused on three
   declared floors, with the shortfall on each.
2. **The cheap configuration is worse per successful outcome** — not 13× worse,
   as in the contract workload. Undefined. It produced nothing usable.
3. **Onboarding is a policy entry and two adapters** — proved against a separate
   application, on a separate port, with zero core files changed.

---

## Reset

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/reset   # control plane → fixtures
curl -X POST http://127.0.0.1:8100/atlas/admin/clear    # ATLAS → empty
```

`admin/reset` re-reads `policy.yaml`, so you can edit a floor and re-run the
promotion board live.
