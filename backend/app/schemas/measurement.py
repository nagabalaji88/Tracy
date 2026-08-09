"""Pydantic DTOs. These exist only at the API boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    use_case: str = Field(..., description="Key into policy.yaml")
    baseline_config_id: str
    candidate_config_id: str
    environment: str = "eval"


class FloorRecord(BaseModel):
    metric: str
    label: str
    direction: str
    floor: float
    candidate_value: float
    baseline_value: float | None = None
    shortfall: float | None = None
    n: int | None = None


class DecisionReason(BaseModel):
    code: str
    metric: str
    detail: str
    magnitude: float | None = None


class PromotionDecision(BaseModel):
    decision: str
    baseline_config_id: str
    candidate_config_id: str
    headline: str
    reasons: list[DecisionReason]
    warnings: list[dict[str, Any]]
    failed_floors: list[FloorRecord]
    passed_floors: list[FloorRecord]
    latency_breach: dict[str, Any] | None = None
    cost_delta_pct: float
    cost_saving_usd: float
    n_paired_documents: int


class EvaluationResponse(BaseModel):
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    comparison: dict[str, Any]
    decision: PromotionDecision


class BoardResponse(BaseModel):
    """The hero screen: three configurations side by side, one of them rejected."""

    use_case: str
    environment: str
    policy: dict[str, Any]
    baseline: dict[str, Any]
    candidates: list[dict[str, Any]]
    generated_from: dict[str, Any]
