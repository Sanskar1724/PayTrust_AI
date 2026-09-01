"""api/schemas.py — Pydantic input/output models for the PayTrust AI HTTP service."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from models.payment_request import PaymentRequest


class EvaluateRequest(PaymentRequest):
    """A payment to evaluate, plus optional advisory AI investigation.

    Inherits all validation from `models/payment_request.PaymentRequest`
    (request_id, amount ≥ 1, currency INR, category enum, user/agent/merchant).
    """

    investigate: bool = False


class EvaluateResponse(BaseModel):
    request_id: str
    decision: str
    risk_score: int
    risk_level: str
    reasons: list[str] = []
    requires_approval: bool = False
    policy_result: dict[str, Any] = {}
    risk_result: dict[str, Any] = {}
    simulation: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    processing_ms: float = 0.0
    duplicate: bool = False
    simulated_estimates: bool = True
    disclaimer: str = (
        "Decision is deterministic (LLM never overrides). AI explanation is advisory only. "
        "Simulator costs are SIMULATED/ESTIMATED — not real financial forecasts. "
        "Any Razorpay action would be TEST MODE only."
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: dict[str, Any] | None = None


class ReadyResponse(BaseModel):
    ready: bool
    database: bool = False
    models: dict[str, bool] = {}
    checks: list[str] = []