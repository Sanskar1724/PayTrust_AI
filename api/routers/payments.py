"""api/routers/payments.py — Payment history + detail (evidence view)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.security import api_key_dependency
from api.service import get_payment_detail, list_payments

router = APIRouter(prefix="/v1/payments", tags=["payments"])


@router.get("", summary="List recent payment evaluations")
def payments_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    _key: str = Depends(api_key_dependency),
):
    db_path = getattr(request.app.state, "db_path", None)
    rows = list_payments(limit=limit, db_path=db_path)
    return {"items": rows, "count": len(rows)}


@router.get("/{request_id}", summary="Full payment evidence detail")
def payments_detail(request_id: str, request: Request, _key: str = Depends(api_key_dependency)):
    db_path = getattr(request.app.state, "db_path", None)
    detail = get_payment_detail(request_id, db_path=db_path)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": f"request_id {request_id} not found"})
    return detail