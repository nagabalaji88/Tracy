"""
ATLAS API.  uvicorn atlas.server:app --port 8100

Separate application, separate port, separate store. It shares no code with the
control plane and does not import it — which is what makes the onboarding claim
testable rather than rhetorical.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from atlas import store
from atlas.flaws import summary as flaw_summary
from atlas.model_client import get_client
from atlas.pipeline import PROFILES, AtlasRun
from atlas.universe import UNIVERSE, tickers

app = FastAPI(
    title="ATLAS — Analyst Toolkit for Long-form Automated Screening",
    version="3.2.1",
    description="Issuer risk memo generation for the research desk.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://127.0.0.1:8000")


@app.get("/atlas/health")
def health() -> dict[str, str]:
    return {"status": "ok", "client": get_client().name}


@app.get("/atlas/universe")
def universe() -> list[dict[str, Any]]:
    return [
        {
            "ticker": i.ticker, "name": i.name, "sector": i.sector,
            "filing_pages": i.filing_pages, "figures": i.figures,
            "disclosures": i.disclosures, "complexity": i.complexity,
            "peers": list(i.peers),
            # Surfaced so the operator can see the runaway coming.
            "peer_graph_cyclic": any(
                i.ticker in UNIVERSE[p].peers for p in i.peers if p in UNIVERSE),
        }
        for i in (UNIVERSE[t] for t in tickers())
    ]


@app.get("/atlas/profiles")
def profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": p.id, "label": p.label, "note": p.note,
            "model_by_stage": p.model_by_stage,
            "filing_extract_pages": p.filing_extract_pages,
            "max_peers": p.max_peers,
            "peer_depth_limit": p.peer_depth_limit,
            "memo_max_tokens": p.memo_max_tokens,
            "reasoning": p.reasoning,
        }
        for p in PROFILES.values()
    ]


@app.get("/atlas/flaws")
def flaws() -> dict[str, Any]:
    return flaw_summary()


@app.get("/atlas/run/stream")
async def run_stream(ticker: str = Query(...), profile: str = Query(default="standard")):
    """
    Execute a run and stream it. Server-sent events, one JSON object per event.

    Event kinds: run_start, stage_start, delta, tool_call, debug_retry,
    hard_stop, stage_end, run_end, error.
    """
    try:
        run = AtlasRun(ticker, profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def events():
        try:
            async for kind, payload in run.stream():
                yield f"data: {json.dumps({'kind': kind, **payload})}\n\n"
                await asyncio.sleep(0)
            store.save(run.record)
            yield f"data: {json.dumps({'kind': 'saved', 'run_id': run.record['run_id']})}\n\n"
        except Exception as exc:  # pragma: no cover - surfaced to the terminal
            yield f"data: {json.dumps({'kind': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/atlas/runs")
def runs() -> list[dict[str, Any]]:
    return store.run_list()


@app.get("/atlas/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    try:
        return store.load(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc


@app.get("/atlas/cost-report")
def cost_report() -> dict[str, Any]:
    return store.cost_report()


@app.get("/atlas/export")
def export() -> dict[str, Any]:
    """The debug records, in ATLAS's own shape. This is what the adapter reads."""
    records = store.load_all()
    return {
        "source": "atlas",
        "source_version": app.version,
        "schema": "atlas.debug_record/v1",
        "runs": records,
        "note": (
            "ATLAS's native format. No trace ids, no cost, no outcome, no policy — "
            "an adapter's job is to map this onto the control plane's spine."
        ),
    }


@app.post("/atlas/handoff")
async def handoff() -> dict[str, Any]:
    """
    Push every recorded run to the control plane's ingest endpoint.

    ATLAS knows one thing about the control plane: a URL. No shared library, no
    shared schema, no shared database.
    """
    import httpx

    records = store.load_all()
    if not records:
        raise HTTPException(status_code=400, detail="no runs recorded yet — execute one first")
    payload = {"source": "atlas", "schema": "atlas.debug_record/v1", "runs": records}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{CONTROL_PLANE_URL}/api/v1/ingest/atlas", json=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"control plane unreachable at {CONTROL_PLANE_URL}: {exc}",
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"sent": len(records), "control_plane": CONTROL_PLANE_URL, "result": resp.json()}


@app.post("/atlas/admin/clear")
def clear() -> dict[str, int]:
    return {"deleted": store.clear()}
