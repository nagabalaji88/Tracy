# ATLAS — Analyst Toolkit for Long-form Automated Screening

A production-shaped equity-research agent for a sell-side research desk. Seven
stages, streamed live, producing an issuer risk memo:

```
resolve_entity → fetch_filings → extract_financials → peer_comparison
               → risk_scoring → compliance_check → draft_memo
```

**It is deliberately, thoroughly flawed** — twelve documented flaws, each one a
pattern that ships in real internal LLM systems for real reasons. It reports what
these systems actually report: elapsed time, a token count, an estimated cost,
and a green ✓ COMPLETE.

This is the subject. The control plane in `../backend` is the instrument.

---

## Run it

```bash
cd agent-atlas/backend
pip install -r requirements.txt
PYTHONPATH=. uvicorn atlas.server:app --port 8100      # API

cd agent-atlas/frontend && npm install && npm run dev   # terminal on :5174
```

Seed operating history (the golden-set list is fetched from the control plane's
`policy.yaml`, because ATLAS has none of its own — that is flaw F12):

```bash
cd agent-atlas/backend
ATLAS_SPEED=0 PYTHONPATH=. python -m atlas.batch --mode both --days 21 --clear
```

`ATLAS_SPEED` compresses the streaming delay. Use `0` for seeding, leave it at
the default `0.5` for the live demo.

---

## Watch it fail

Open the terminal, pick **NRTH** (Northgate Financial Group) on the **STANDARD**
profile, and press EXECUTE.

Financials-sector issuers have cyclic peer graphs. `peer_comparison` recurses
into each peer's peers with no visited set and no depth cap, re-sending the
accumulated transcript on every hop. You will watch it walk `HRBR → NRTH → HRBR`
to depth 18, burn 8.4M tokens and $33.86 in twelve seconds, and finish with a
green ✓ COMPLETE.

Nothing raised. So the run is fine.

Then switch to **COST-OPTIMIZED** — the profile shipped on a Friday to bring
spend under the monthly cap. It is genuinely, measurably cheaper. Nothing in
ATLAS can tell you what it cost in quality, because ATLAS has no idea what
quality is.

---

## The twelve flaws

`GET /atlas/flaws`, or the KNOWN GAPS tab. Each entry states what ATLAS does, why
a competent team would have done that, what it costs, and which part of the
control plane notices.

| | Flaw | Caught by |
|---|---|---|
| F01 | Cost estimated from one flat token rate | Module 2 — per-model metering |
| F02 | No attribution below the run | Module 2 — rollups |
| F03 | Success means the process did not crash | Module 1 — outcomes |
| F04 | Retries swallowed inside the stage | Module 2 — retry bucket |
| F05 | Filing preamble re-sent fresh every stage | Module 2/4 — cache split & lever |
| F06 | Peer recursion with no depth cap or visited set | Module 5 — loop detection |
| F07 | Config changes ship straight to production | Module 1 — promotion decision |
| F08 | The only budget control is a monthly total | Module 3/5 — ladder & velocity |
| F09 | No latency ceiling | Module 1/4 — ceiling & pre-flight |
| F10 | The memo is truncated silently | Module 1 — truncation floor |
| F11 | Analyst rework recorded in a different system | Module 1/2 — rework in numerator |
| F12 | There is no golden set | Module 1 — paired evaluation |

The flaws are implemented in `atlas/pipeline.py`, not simulated. `_peer_pass`
really has no visited set; `_call_with_retry` really returns only the winner;
`draft_memo` really ignores the `finish_reason` sitting in the response it just
received.

---

## Hand it to the control plane

Press **↗ SEND RUNS**, or:

```bash
curl -X POST http://127.0.0.1:8100/atlas/handoff
```

ATLAS POSTs its debug records to `http://127.0.0.1:8000/api/v1/ingest/atlas`. It
knows exactly one thing about the control plane: a URL. No shared library, no
shared schema, no shared database.

What the control plane does with them is in `../DEMO.md`.

---

## Where the numbers come from

Token counts, latencies and finish reasons come from `SimulatedClient` — a
seeded, deterministic model of the pipeline that streams in real time — because
this environment has no model credentials. `LiveClient` is implemented alongside
it; set `ATLAS_CLIENT=live` with `ANTHROPIC_API_KEY` and the per-tier model ids
to record against a real endpoint. The shape of what ATLAS records is identical
either way, which is the part the adapter consumes.

Issuers are **fictional**. Tickers, sectors, filing sizes, peer graphs and every
"extracted" financial figure are invented for this demo. Attaching fabricated
fundamentals to a real listed company would produce something that reads like
research and is not.

---

## Layout

```
backend/atlas/
  flaws.py         the registry — what, why it shipped, what it costs, who catches it
  universe.py      fictional issuers and the cyclic peer graph
  model_client.py  SimulatedClient | LiveClient, and the flat-rate cost estimate (F01)
  pipeline.py      the seven stages, with the flaws implemented
  store.py         the debug record, and the monthly report that ignores it
  server.py        SSE stream, run history, cost report, handoff
  batch.py         seeds production history and golden-set runs
frontend/src/
  App.tsx          the terminal
  terminal.css     dark, dense, square-cornered, monospace
```
