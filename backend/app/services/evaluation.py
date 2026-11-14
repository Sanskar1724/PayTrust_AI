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
from datetime import date, timedelta
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
from app.domain.policy import Spend, evaluate_policy
from app.domain.risk import DUPLICATE_WINDOW_MINUTES, assess_risk
from app.errors import Conflict, NotFound, ValidationFailed
from app.log import get_logger
from app.metrics import DECISIONS
from app.models import Agent, Merchant, Payment, PaymentStatus, Policy, User
from app.schemas import PaymentIn
from app.services import audit, job_handlers, jobs
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


def period_bounds(day: str) -> dict[str, tuple[str, str]]:
    """The day, its Monday–Sunday week and its calendar month, as inclusive spend_day ranges."""
    d = date.fromisoformat(day)
    week_start = d - timedelta(days=d.weekday())
    month_start = d.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return {
        "day": (day, day),
        "week": (week_start.isoformat(), (week_start + timedelta(days=6)).isoformat()),
        "month": (month_start.isoformat(), (next_month - timedelta(days=1)).isoformat()),
    }


def spend_snapshot(session: Session, user_id: int, agent_id: int, day: str,
                   exclude_payment_id: int | None = None) -> tuple[Spend, Spend]:
    """(this agent's spend, the user's spend across all agents) for the day, week and month that
    contain `day`. Counts ALLOWED + PENDING_APPROVAL + APPROVED; never the excluded payment."""
    bounds = period_bounds(day)
    lo = min(b[0] for b in bounds.values())
    hi = max(b[1] for b in bounds.values())
    stmt = select(Payment.spend_day, Payment.agent_id, Payment.amount).where(
        Payment.user_id == user_id,
        Payment.spend_day >= lo,
        Payment.spend_day <= hi,
        Payment.status.in_(PaymentStatus.COUNTS_TOWARD_SPEND),
    )
    if exclude_payment_id is not None:
        stmt = stmt.where(Payment.id != exclude_payment_id)
    agent = {p: 0 for p in bounds}
    total = {p: 0 for p in bounds}
    for spent_day, pay_agent, amount in session.execute(stmt):
        for period, (start, end) in bounds.items():
            if start <= spent_day <= end:
                total[period] += amount
                if pay_agent == agent_id:
                    agent[period] += amount
    return Spend(**agent), Spend(**total)


def gather_context(session: Session, user_id: int, agent_id: int, merchant_id: int, amount: int,
                   now) -> dict[str, Any]:
    """Payer history, read inside the locked transaction. The new payment is not yet written."""
    agent_spend, user_spend = spend_snapshot(session, user_id, agent_id, spend_day(now))
    daily_spent = agent_spend.day
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
        "agent_spend": agent_spend,
        "user_spend": user_spend,
        "transactions_last_hour": int(attempts_last_hour or 0),
        "duplicates_recent": int(duplicates or 0),
        "user_total_txns": int(successful or 0),
        "is_new_merchant": int(with_merchant or 0) == 0,
        "is_new_user": int(successful or 0) == 0,
    }


def _evaluate_in_session(session: Session, req: PaymentIn, agent_id: int, key_agent_id: int | None,
                         key_id: int | None, source: str, actor: str, digest: str) -> tuple[Payment, bool]:
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

    context = gather_context(session, req.user_id, agent_id, req.merchant_id, req.amount, now)
    context["daily_limit"] = policy.daily_limit if policy else None

    # The agent supplies merchant_name, but only the registered name is trusted for policy
    # matching, storage and display; the claimed name is kept as evidence.
    payment_facts = req.model_dump() | {
        "agent_id": agent_id,
        "merchant_name": merchant.name if merchant else req.merchant_name,
        "claimed_merchant_name": req.merchant_name,
        "merchant_category": merchant.category if merchant else None,
        "merchant_risk_tier": merchant.risk_tier if merchant else None,
    }
    policy_result = evaluate_policy(policy.as_rules() if policy else None, payment_facts,
                                    preconditions=preconditions, agent_spend=context.pop("agent_spend"),
                                    user_spend=context.pop("user_spend"),
                                    user_budget=user.budget() if user else None)
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
        api_key_id=key_id,
        merchant_id=req.merchant_id,
        merchant_name=payment_facts["merchant_name"],
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
    # Follow-up work is queued in this same transaction: it exists if and only if the decision does.
    if status in PaymentStatus.SUCCESSFUL:
        job_handlers.enqueue_order(session, req.request_id)
    elif status == PaymentStatus.PENDING_APPROVAL and get_settings().AI_AUTO_INVESTIGATE:
        job_handlers.enqueue_ai(session, req.request_id)
    audit.record(session, actor, "PAYMENT_EVALUATED", req.request_id, decision=decision["decision"],
                 status=status, amount=req.amount, risk_score=decision["risk_score"], source=source)
    session.flush()
    return payment, True


def evaluate_payment(req: PaymentIn, *, key_agent_id: int | None, source: str, actor: str,
                     key_id: int | None = None) -> tuple[Payment, bool]:
    """Evaluate (or idempotently replay) one payment. Returns (payment, created)."""
    agent_id = req.agent_id or key_agent_id
    if agent_id is None:
        raise ValidationFailed("agent_id is required")
    digest = body_hash(req.model_dump() | {"agent_id": agent_id})
    try:
        with session_scope() as session:
            payment, created = _evaluate_in_session(session, req, agent_id, key_agent_id, key_id, source, actor,
                                                     digest)
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
        jobs.kick()
    return payment, created


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
