"""api/routers/evaluate.py — POST /v1/evaluate (the merchant-facing decision API)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.schemas import EvaluateRequest, EvaluateResponse
from api.security import api_key_dependency
from api.service import evaluate_payment
from core.exceptions import PayTrustError
from pydantic import ValidationError as PydanticValidationError

router = APIRouter(prefix="/v1", tags=["evaluate"])


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Evaluate a payment → Policy / Risk / Decision (+ optional advisory AI)",
    description=(
        "Runs the deterministic pipeline: PaymentRequest validation → PolicyEngine → "
        "RiskEngine → DecisionEngine → DecisionSimulator. Returns ALLOW / ASK_USER / DENY "
        "with evidence (policy_result, risk factors, counterfactuals). "
        "Set `investigate: true` to also run the ADVISORY AI explanation (LLM never overrides)."
    ),
)
def evaluate(payload: EvaluateRequest, request: Request, _key: str = Depends(api_key_dependency)):
    db_path = getattr(request.app.state, "db_path", None)
    try:
        result = evaluate_payment(payload.model_dump(), db_path=db_path)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "errors": exc.errors()},
        )
    except PayTrustError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": str(exc)[:500]},
        )
    except Exception as exc:  # unexpected → still safe, no secrets
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)[:300]},
        )
    return result