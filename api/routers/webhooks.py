"""api/routers/webhooks.py — Razorpay webhook ingestion (raw body, HMAC, idempotent)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status

from services.razorpay_service import handle_webhook

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post(
    "/razorpay",
    summary="Razorpay webhook (HMAC raw-body verified, idempotent)",
    description=(
        "Verifies `X-Razorpay-Signature` over the RAW body before parsing (constant-time). "
        "Duplicate events are ignored safely. Never logs the body or secrets."
    ),
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
):
    if not x_razorpay_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"status": "rejected", "reason": "missing_signature"})
    raw = await request.body()
    db_path = getattr(request.app.state, "db_path", None)
    result = handle_webhook(raw, x_razorpay_signature, db_path=db_path)
    if result.get("status") == "rejected":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    if result.get("status") == "duplicate":
        return result  # 200 — idempotent ignore, Razorpay stops retrying
    return result