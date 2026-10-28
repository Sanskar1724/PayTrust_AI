"""The one evaluation pipeline. Every caller (agent API, operator playground, Agent Arena)
goes through `evaluate_payment`.

Guarantees:
  * Atomic — request, decision, evidence and audit entry are written in one transaction.
  * Serialized per payer — the payer row is locked before budget is read, so concurrent
    payments can never jointly exceed the daily limit.
  * Context excludes the payment being evaluated — no double counting.
  * Idempotent — same request_id + same body returns the stored decision; a different
    body under the same request_id is rejected with 409.
  * Fail-closed — if anything fails, no decision is issued (the caller gets an error,
    never a silent ALLOW).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.domain.counterfactual import simulate
from app.domain.decision import decide
from app.domain.explain import build_facts
from app.domain.policy import evaluate_policy
from app.domain.risk import DUPLICATE_WINDOW_MINUTES, assess_risk
from app.errors import Conflict, NotFound, ValidationFailed
from app.log import get_logger
from app.metrics import DECISIONS
from app.models import Agent, Merchant, Payment, PaymentStatus, Policy, User
from app.schemas import PaymentIn
from app.services import audit, tasks
from app.services.events import bus

logger = get_logger("evaluation")

STATUS_FOR_DECISION = {
    "ALLOW": PaymentStatus.ALLOWED,
    "ASK_USER": PaymentStatus.PENDING_APPROVAL,
    "DENY": PaymentStatus.DENIED,
}


def spend_day(now=None) -> str:
    now = now or utcnow()
    return now.astimezone(ZoneInfo(get_settings().SPEND_TIMEZONE)).date().isoformat()


def body_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gather_context(session: Session, user_id: int, merchant_id: int, amount: int, now) -> dict[str, Any]:
    """Payer history, read inside the locked transaction. The new payment is not yet written."""
    daily_spent = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.user_id == user_id,
            Payment.spend_day == spend_day(now),
            Payment.status.in_(PaymentStatus.COUNTS_TOWARD_SPEND),
        )
    )
    attempts_last_hour = session.scalar(
        select(func.count()).select_from(Payment).where(
            Payment.user_id == user_id, Payment.created_at >= now - timedelta(hours=1)
        )
    )
    duplicates = session.scalar(
        select(func.count()).select_from(Payment).where(
            Payment.user_id == user_id,
            Payment.merchant_id == merchant_id,
            Payment.amount == amount,
            Payment.created_at >= now - timedelta(minutes=DUPLICATE_WINDOW_MINUTES),
        )
    )
    successful = session.scalar(
        select(func.count()).select_from(Payment).where(
            Payment.user_id == user_id, Payment.status.in_(PaymentStatus.SUCCESSFUL)
        )
    )
    with_merchant = session.scalar(
        select(func.count()).select_from(Payment).where(
            Payment.user_id == user_id,
            Payment.merchant_id == merchant_id,
            Payment.status.in_(PaymentStatus.SUCCESSFUL),
        )
    )
    return {
        "daily_spent": int(daily_spent or 0),
        "transactions_last_hour": int(attempts_last_hour or 0),
        "duplicates_recent": int(duplicates or 0),
        "user_total_txns": int(successful or 0),
        "is_new_merchant": int(with_merchant or 0) == 0,
        "is_new_user": int(successful or 0) == 0,
    }


def _evaluate_in_session(session: Session, req: PaymentIn, agent_id: int, key_agent_id: int | None,
                         source: str, actor: str, digest: str) -> tuple[Payment, bool]:
    existing = session.scalar(select(Payment).where(Payment.request_id == req.request_id))
    if existing is not None:
        if existing.body_hash != digest:
            raise Conflict(f"request_id '{req.request_id}' was already used with a different request body")
        return existing, False

    started = time.perf_counter()
    now = utcnow()

    # Lock the payer (PostgreSQL row lock; SQLite already holds the write lock via BEGIN IMMEDIATE).
    user = session.scalar(select(User).where(User.id == req.user_id).with_for_update())
    agent = session.get(Agent, agent_id)
    merchant = session.get(Merchant, req.merchant_id)
    policy = session.scalar(select(Policy).where(Policy.user_id == req.user_id, Policy.agent_id == agent_id))

    preconditions: list[tuple[str, str]] = []
    if user is None:
        preconditions.append(("missing_user", f"User {req.user_id} does not exist."))
    if agent is None or not agent.is_active:
        preconditions.append(("unauthorized_agent", f"Agent {agent_id} does not exist or is disabled."))
    if key_agent_id is not None and agent_id != key_agent_id:
        preconditions.append(("agent_key_mismatch", "The API key belongs to a different agent than the request names."))
    if merchant is None:
        preconditions.append(("missing_merchant", f"Merchant {req.merchant_id} does not exist."))

    context = gather_context(session, req.user_id, req.merchant_id, req.amount, now)
    context["daily_limit"] = policy.daily_limit if policy else None

    payment_facts = req.model_dump() | {
        "agent_id": agent_id,
        "merchant_category": merchant.category if merchant else None,
        "merchant_risk_tier": merchant.risk_tier if merchant else None,
    }
    policy_result = evaluate_policy(policy.as_rules() if policy else None, payment_facts,
                                    context["daily_spent"], preconditions)
    risk_result = assess_risk(payment_facts, policy_result, context)
    risk_result["context"] = {k: v for k, v in context.items() if k != "daily_limit"}
    decision = decide(policy_result, risk_result)
    simulation = simulate(payment_facts, policy_result, risk_result)

    status = STATUS_FOR_DECISION[decision["decision"]]
    ttl = timedelta(minutes=get_settings().APPROVAL_TTL_MINUTES)
    payment = Payment(
        request_id=req.request_id,
        body_hash=digest,
        source=source,
        user_id=req.user_id,
        agent_id=agent_id,
        merchant_id=req.merchant_id,
        merchant_name=req.merchant_name,
        amount=req.amount,
        currency=req.currency,
        category=req.category,
        description=req.description,
        agent_reason=req.agent_reason,
        callback_url=req.callback_url,
        status=status,
        decision=decision["decision"],
        risk_score=decision["risk_score"],
        risk_level=decision["risk_level"],
        reasons=decision["reasons"],
        policy_result=policy_result,
        risk_result=risk_result,
        simulation=simulation,
        spend_day=spend_day(now),
        expires_at=now + ttl if status == PaymentStatus.PENDING_APPROVAL else None,
        created_at=now,
        updated_at=now,
    )
    payment.processing_ms = round((time.perf_counter() - started) * 1000, 2)
    session.add(payment)
    audit.record(session, actor, "PAYMENT_EVALUATED", req.request_id, decision=decision["decision"],
                 status=status, amount=req.amount, risk_score=decision["risk_score"], source=source)
    session.flush()
    return payment, True


def evaluate_payment(req: PaymentIn, *, key_agent_id: int | None, source: str, actor: str) -> tuple[Payment, bool]:
    """Evaluate (or idempotently replay) one payment. Returns (payment, created)."""
    agent_id = req.agent_id or key_agent_id
    if agent_id is None:
        raise ValidationFailed("agent_id is required")
    digest = body_hash(req.model_dump() | {"agent_id": agent_id})
    try:
        with session_scope() as session:
            payment, created = _evaluate_in_session(session, req, agent_id, key_agent_id, source, actor, digest)
    except IntegrityError as exc:
        # Lost a race on the same request_id — the winner's row is the answer.
        with session_scope() as session:
            payment = session.scalar(select(Payment).where(Payment.request_id == req.request_id))
            if payment is None:
                raise
            if payment.body_hash != digest:
                raise Conflict(f"request_id '{req.request_id}' was already used with a different request body") from exc
            created = False

    if created:
        logger.info(f"{payment.request_id} → {payment.decision} risk={payment.risk_score} in {payment.processing_ms}ms")
        DECISIONS.labels(payment.decision, source).inc()
        bus.publish("payment.created", summary(payment))
        tasks.submit(post_process, payment.request_id)
    return payment, created


def post_process(request_id: str) -> None:
    """Follow-up work off the request path: Razorpay order for approved money movement,
    AI explanation for payments waiting on a human. Safe to run more than once."""
    from app.services import ai, razorpay

    s = get_settings()
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        if payment is None:
            return
        amount = payment.amount
        needs_order = payment.status in PaymentStatus.SUCCESSFUL and payment.order is None
        needs_ai = payment.status == PaymentStatus.PENDING_APPROVAL and payment.ai is None and s.AI_AUTO_INVESTIGATE
        facts = facts_for(session, payment) if needs_ai else None

    order = None
    if needs_order:
        try:
            order = razorpay.create_order(request_id, amount, {"paytrust_request_id": request_id})
        except Exception as exc:
            order = {"status": "error", "error": str(exc)[:300]}
            logger.warning(f"Order creation failed for {request_id}: {exc}")
    ai_result = ai.get_investigator().investigate(facts) if facts else None

    if order is None and ai_result is None:
        return
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id).with_for_update())
        if order is not None and payment.order is None:
            payment.order = order
            audit.record(session, "system", "ORDER_CREATED" if order.get("status") != "error" else "ORDER_FAILED",
                         request_id, order_id=order.get("id"), mode=order.get("mode"))
        if ai_result is not None and payment.ai is None:
            payment.ai = ai_result
        updated = summary(payment)
    bus.publish("payment.updated", updated)


def investigate_now(request_id: str, actor: str) -> Payment:
    """Operator-requested (re-)investigation, synchronous."""
    from app.services import ai

    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        if payment is None:
            raise NotFound(f"Payment '{request_id}' not found")
        facts = facts_for(session, payment)
    result = ai.get_investigator().investigate(facts)
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        payment.ai = result
        audit.record(session, actor, "AI_INVESTIGATED", request_id, provider=result["provider"])
    bus.publish("payment.updated", summary(payment))
    return payment


def facts_for(session: Session, payment: Payment) -> dict[str, Any]:
    merchant = session.get(Merchant, payment.merchant_id)
    snapshot = summary(payment) | {
        "description": payment.description,
        "agent_reason": payment.agent_reason,
        "merchant_category": merchant.category if merchant else None,
    }
    return build_facts(snapshot, payment.policy_result, payment.risk_result,
                       {"decision": payment.decision, "reasons": payment.reasons})


def summary(p: Payment) -> dict[str, Any]:
    return {
        "request_id": p.request_id,
        "status": p.status,
        "decision": p.decision,
        "risk_score": p.risk_score,
        "risk_level": p.risk_level,
        "user_id": p.user_id,
        "agent_id": p.agent_id,
        "merchant_id": p.merchant_id,
        "merchant_name": p.merchant_name,
        "amount": p.amount,
        "category": p.category,
        "source": p.source,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "processing_ms": p.processing_ms,
    }
