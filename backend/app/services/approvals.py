"""ASK_USER lifecycle: PENDING_APPROVAL → APPROVED | REJECTED | EXPIRED.

A pending payment already reserves its amount against the daily limit, so approving
it can never push the payer over budget. Rejection or expiry releases the reservation.

Approval re-checks the mandate at the moment money would move: the agent, its API key,
the user, the merchant and the CURRENT policy must all still permit the payment. Risk is
not re-scored: overriding risk is exactly what the reviewer is there for. If anything no
longer holds, the payment is rejected by the system and the reviewer gets a 409.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.domain.policy import evaluate_policy
from app.errors import Conflict, NotFound
from app.log import get_logger
from app.models import Agent, ApiKey, Merchant, Payment, PaymentStatus, Policy, User
from app.services import audit, job_handlers, jobs
from app.services.evaluation import spend_snapshot, summary
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
            job_handlers.enqueue_callback(session, request_id)  # the agent must hear about the expiry too
            session.commit()
            jobs.kick()
            raise Conflict("This approval request has expired")
        if payment.status != PaymentStatus.PENDING_APPROVAL:
            raise Conflict(f"Payment is {payment.status}; only PENDING_APPROVAL payments can be reviewed")
        blockers = approval_blockers(session, payment) if approve else []
        if blockers:
            payment.status = PaymentStatus.REJECTED
            payment.reviewed_by = "system"
            payment.reviewed_at = now
            payment.review_note = "Approval blocked: " + " ".join(blockers)
            audit.record(session, actor, "APPROVAL_BLOCKED", request_id, reasons=blockers, note=note)
            job_handlers.enqueue_callback(session, request_id)
        else:
            payment.status = PaymentStatus.APPROVED if approve else PaymentStatus.REJECTED
            payment.reviewed_by = actor
            payment.reviewed_at = now
            payment.review_note = note
            audit.record(session, actor, "PAYMENT_APPROVED" if approve else "PAYMENT_REJECTED", request_id, note=note)
            if approve:  # create the order first; its job then queues the callback, which carries the order
                job_handlers.enqueue_order(session, request_id, notify=True)
            else:
                job_handlers.enqueue_callback(session, request_id)
        event = summary(payment)

    bus.publish("payment.updated", event)
    jobs.kick()
    if blockers:
        logger.warning(f"{request_id} approval by {actor} blocked: {blockers}")
        raise Conflict("Approval blocked — the payment was rejected because it is no longer permitted: "
                       + " ".join(blockers))
    logger.info(f"{request_id} {'approved' if approve else 'rejected'} by {actor}")
    return payment


def approval_blockers(session: Session, payment: Payment) -> list[str]:
    """Reasons this pending payment may no longer be approved (empty list = OK to approve)."""
    blockers: list[str] = []
    agent = session.get(Agent, payment.agent_id)
    if agent is None or not agent.is_active:
        blockers.append(f"Agent {payment.agent_id} is disabled or was deleted.")
    if payment.api_key_id is not None:
        key = session.get(ApiKey, payment.api_key_id)
        if key is None or key.revoked_at is not None:
            blockers.append("The API key that submitted this payment has been revoked.")
    user = session.get(User, payment.user_id)
    if user is None:
        blockers.append(f"User {payment.user_id} no longer exists.")
    merchant = session.get(Merchant, payment.merchant_id)
    if merchant is None:
        blockers.append(f"Merchant {payment.merchant_id} no longer exists.")
    policy = session.scalar(select(Policy).where(Policy.user_id == payment.user_id,
                                                 Policy.agent_id == payment.agent_id))
    if policy is None:
        blockers.append("The policy for this user and agent was removed.")
        return blockers

    # This payment already reserves its amount; measure everything else spent in its periods.
    agent_spend, user_spend = spend_snapshot(session, payment.user_id, payment.agent_id, payment.spend_day,
                                             exclude_payment_id=payment.id)
    facts = {
        "amount": payment.amount,
        "category": payment.category,
        "merchant_id": payment.merchant_id,
        "merchant_name": merchant.name if merchant else payment.merchant_name,
        "merchant_category": merchant.category if merchant else None,
    }
    result = evaluate_policy(policy.as_rules(), facts, agent_spend=agent_spend, user_spend=user_spend,
                             user_budget=user.budget() if user else None)
    # Each violation appends exactly one reason, in order, before any informational note.
    blockers.extend(result["reasons"][:len(result["violations"])])
    return blockers


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
            job_handlers.enqueue_callback(session, payment.request_id)
        expired = [summary(p) for p in due]
    for event in expired:
        bus.publish("payment.updated", event)
    if expired:
        jobs.kick()
    if expired:
        logger.info(f"Expired {len(expired)} pending approvals")
    return len(expired)
