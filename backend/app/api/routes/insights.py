"""Dashboard stats, audit trail, ML threshold tool, live event stream, Razorpay webhooks."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_operator, operator_from_query_token
from app.db import get_session, session_scope
from app.models import AuditEvent, Operator
from app.schemas import AuditOut, Page
from app.services import ml, razorpay, stats
from app.services.events import bus

router = APIRouter(prefix="/v1")
HEARTBEAT_SECONDS = 15


@router.get("/stats", tags=["insights"], summary="Dashboard metrics for the last 24 hours")
def get_stats(_: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return stats.dashboard(session)


@router.get("/audit", response_model=Page, tags=["insights"])
def get_audit(
    event_type: str | None = None,
    request_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Operator = Depends(current_operator),
    session: Session = Depends(get_session),
):
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if request_id:
        stmt = stmt.where(AuditEvent.request_id == request_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=total or 0, limit=limit, offset=offset)


@router.get("/ml/report", tags=["ml"], summary="IEEE-CIS held-out evaluation report")
def ml_report(_: Operator = Depends(current_operator)):
    return ml.report()


@router.get("/ml/curves", tags=["ml"], summary="Metrics across all thresholds (0.00–1.00)")
def ml_curves(_: Operator = Depends(current_operator)):
    return ml.curves()


@router.get("/ml/metrics", tags=["ml"], summary="Metrics at one threshold")
def ml_metrics(threshold: float = Query(ge=0.0, le=1.0), _: Operator = Depends(current_operator)):
    return ml.metrics_at(threshold) | {"disclaimer": ml.DISCLAIMER}


@router.get("/stream", tags=["insights"], summary="Live decision feed (Server-Sent Events)")
async def stream(request: Request, _: Operator = Depends(operator_from_query_token)):
    async def events():
        yield "retry: 3000\n\n"
        subscription = bus.subscribe()
        pending = asyncio.ensure_future(anext(subscription))
        try:
            while not await request.is_disconnected():
                done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
                if not done:
                    yield ": ping\n\n"
                    continue
                event = pending.result()
                pending = asyncio.ensure_future(anext(subscription))
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'], default=str)}\n\n"
        finally:
            pending.cancel()
            await subscription.aclose()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/webhooks/razorpay", tags=["webhooks"], summary="Razorpay webhook (HMAC over raw body, idempotent)")
async def razorpay_webhook(request: Request,
                           x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature")):
    raw = await request.body()  # signature is verified over the exact bytes received

    def ingest():
        with session_scope() as session:
            return razorpay.ingest_webhook(session, raw, x_razorpay_signature)

    return await run_in_threadpool(ingest)
