"""ASK_USER lifecycle: PENDING_APPROVAL → APPROVED | REJECTED | EXPIRED.

A pending payment already reserves its amount against the daily limit, so approving
it can never push the payer over budget. Rejection or expiry releases the reservation.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope, utcnow
from app.errors import Conflict, NotFound
from app.log import get_logger
from app.models import Payment, PaymentStatus
from app.services import audit, callbacks, tasks
from app.services.evaluation import post_process, summary
from app.services.events import bus

logger = get_logger("approvals")


def review(request_id: str, approve: bool, actor: str, note: str | None = None) -> Payment:
    now = utcnow()
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id).with_for_update())
        if payment is None:
            raise NotFound(f"Payment '{request_id}' not found")
        if payment.status == PaymentStatus.PENDING_APPROVAL and payment.expires_at and payment.expires_at <= now:
            payment.status = PaymentStatus.EXPIRED
            audit.record(session, "system", "APPROVAL_EXPIRED", request_id)
            session.commit()
            raise Conflict("This approval request has expired")
        if payment.status != PaymentStatus.PENDING_APPROVAL:
            raise Conflict(f"Payment is {payment.status}; only PENDING_APPROVAL payments can be reviewed")
        payment.status = PaymentStatus.APPROVED if approve else PaymentStatus.REJECTED
        payment.reviewed_by = actor
        payment.reviewed_at = now
        payment.review_note = note
        audit.record(session, actor, "PAYMENT_APPROVED" if approve else "PAYMENT_REJECTED", request_id, note=note)
        event = summary(payment)

    logger.info(f"{request_id} {'approved' if approve else 'rejected'} by {actor}")
    bus.publish("payment.updated", event)
    if approve:
        tasks.submit(_approve_followups, request_id)
    else:
        tasks.submit(callbacks.notify_agent, request_id)
    return payment


def _approve_followups(request_id: str) -> None:
    post_process(request_id)  # creates the order first, so the callback can include it
    callbacks.notify_agent(request_id)


def expire_due() -> int:
    """Mark overdue pending approvals EXPIRED. Called periodically by the app."""
    now = utcnow()
    with session_scope() as session:
        due = session.scalars(
            select(Payment)
            .where(Payment.status == PaymentStatus.PENDING_APPROVAL, Payment.expires_at <= now)
            .with_for_update(skip_locked=True)
            .limit(500)
        ).all()
        for payment in due:
            payment.status = PaymentStatus.EXPIRED
            audit.record(session, "system", "APPROVAL_EXPIRED", payment.request_id)
        expired = [summary(p) for p in due]
    for event in expired:
        bus.publish("payment.updated", event)
        tasks.submit(callbacks.notify_agent, event["request_id"])
    if expired:
        logger.info(f"Expired {len(expired)} pending approvals")
    return len(expired)
