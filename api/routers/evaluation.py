"""api/routers/evaluation.py — Honest, real evaluation numbers for the UI/API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.security import api_key_dependency
from api.service import get_evaluation_reports

router = APIRouter(prefix="/v1/evaluation", tags=["evaluation"])


@router.get(
    "/metrics",
    summary="Model evaluation metrics (IEEE held-out + synthetic demo, never invented)",
)
def metrics(request: Request, _key: str = Depends(api_key_dependency)):
    data = get_evaluation_reports()
    if not data["available"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NO_REPORTS", "message": "evaluation reports not found — train models first (python -m models.train_ieee_chunked)"},
        )
    return data