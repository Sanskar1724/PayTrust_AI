"""api/routers/threshold.py — Threshold Decision Tool (Track-02 rubric: false-positive cost)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.security import api_key_dependency
from models.threshold import best_operating_point, load_test_predictions, metrics_at, sweep, to_curves

router = APIRouter(prefix="/v1/threshold", tags=["threshold"])


def _404_from_missing(exc: FileNotFoundError):
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NO_TEST_PREDS", "message": str(exc)},
    )


@router.get(
    "",
    summary="Metrics at a probability operating point (real IEEE held-out test)",
)
def threshold_at(
    p: float = Query(default=0.95, ge=0.0, le=1.0, alias="p", description="Fraud-probability threshold"),
    _key: str = Depends(api_key_dependency),
):
    try:
        return metrics_at(float(p))
    except FileNotFoundError as exc:
        raise _404_from_missing(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


@router.get(
    "/curves",
    summary="Threshold sweep curves (precision / recall / FPR / costs)",
)
def threshold_curves(
    step: float = Query(default=0.01, ge=0.001, le=0.1, description="Sweep step (0-1)"),
    _key: str = Depends(api_key_dependency),
):
    try:
        return to_curves(sweep(step=float(step)))
    except FileNotFoundError as exc:
        raise _404_from_missing(exc)


@router.get(
    "/recommend",
    summary="Suggested operating points (max F1, min SIMULATED total cost) — labeled as suggestions",
)
def threshold_recommend(_key: str = Depends(api_key_dependency)):
    try:
        return best_operating_point()
    except FileNotFoundError as exc:
        raise _404_from_missing(exc)


@router.get("/check", summary="Check whether test predictions exist (for UI gating)")
def threshold_check(_key: str = Depends(api_key_dependency)):
    try:
        df = load_test_predictions()
        return {"available": True, "rows": len(df), "missing": None}
    except FileNotFoundError as exc:
        return {"available": False, "rows": 0, "missing": str(exc)}