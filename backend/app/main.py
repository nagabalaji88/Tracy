"""
AI Cost-Quality Control Plane — API.

    minimize cost   subject to   quality >= floor   AND   latency <= ceiling

Run:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import attribution, breakers, forecast, measurement, simulator

app = FastAPI(
    title="AI Cost-Quality Control Plane",
    version="1.0.0",
    description=(
        "Cost per successful outcome, not cost per token. The defining behaviour "
        "is that it rejects a cost saving when measured quality falls below a "
        "declared floor."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(measurement.router)
app.include_router(attribution.router)
app.include_router(forecast.router)
app.include_router(simulator.router)
app.include_router(breakers.router)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
