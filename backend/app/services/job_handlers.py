"""The background job kinds. Each handler is idempotent (delivery is at-least-once).

  order.create     ALLOWED / APPROVED payment → Razorpay order. Retried with backoff; once
                   retries run out the payment gets order={"status": "error"} (ORDER_FAILED).
                   payload.notify=True chains a callback after the order (approvals), so the
                   agent's callback carries the order.
  ai.investigate   advisory explanation for a payment waiting on a human.
  callback.notify  signed POST to the agent when a pending payment is resolved. Retried with
                   backoff (CALLBACK_MAX_ATTEMPTS); an unsafe URL is permanent (CALLBACK_BLOCKED).
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.log import get_logger
from app.models import Payment, PaymentStatus
from app.services import audit, jobs
from app.services.events import bus
from app.services.jobs import JobContext

logger = get_logger("jobs")

ORDER_CREATE = "order.create"
AI_INVESTIGATE = "ai.investigate"
CALLBACK_NOTIFY = "callback.notify"


def enqueue_order(session, request_id: str, notify: bool = False) -> None:
    jobs.enqueue(session, ORDER_CREATE, {"request_id": request_id, "notify": notify},
                 request_id=request_id, dedupe_key=f"{ORDER_CREATE}:{request_id}")


def enqueue_ai(session, request_id: str) -> None:
    jobs.enqueue(session, AI_INVESTIGATE, {"request_id": request_id},
                 request_id=request_id, dedupe_key=f"{AI_INVESTIGATE}:{request_id}")


def enqueue_callback(session, request_id: str, reason: str = "resolved") -> None:
    """One callback per payment and reason: sent once the payment is resolved, and once more
    if a failed order is later recovered (reason="order-recovered")."""
    suffix = "" if reason == "resolved" else f":{reason}"
    jobs.enqueue(session, CALLBACK_NOTIFY, {"request_id": request_id},
                 request_id=request_id, dedupe_key=f"{CALLBACK_NOTIFY}:{request_id}{suffix}")


def _has_order(payment: Payment) -> bool:
    """A failed order (status "error", left by a dead job) does not count: a retry replaces it."""
    return payment.order is not None and payment.order.get("status") != "error"


# ── order.create ──

def _store_order(request_id: str, order: dict, event: str, notify: bool) -> None:
    from app.services.evaluation import summary

    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id).with_for_update())
        if payment is None:
            return
        recovered = event == "ORDER_CREATED" and payment.order is not None and not _has_order(payment)
        if not _has_order(payment):
            payment.order = order
            audit.record(session, "system", event, request_id, order_id=order.get("id"), mode=order.get("mode"),
                         error=order.get("error"))
        if notify:
            enqueue_callback(session, request_id, "order-recovered" if recovered else "resolved")
        updated = summary(payment)
    bus.publish("payment.updated", updated)
    if notify:
        jobs.kick()


def _order_dead(job: JobContext, error: str, permanent: bool) -> None:
    """Retries exhausted: record the failure on the payment (and still tell the agent)."""
    order = {"status": "error", "error": error[:300], "attempts": job.attempt}
    _store_order(job.payload["request_id"], order, "ORDER_FAILED", bool(job.payload.get("notify")))


@jobs.handler(ORDER_CREATE, on_dead=_order_dead)
def create_order(job: JobContext) -> None:
    from app.services import razorpay

    request_id, notify = job.payload["request_id"], bool(job.payload.get("notify"))
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        if payment is None:
            return
        if payment.status not in PaymentStatus.SUCCESSFUL or _has_order(payment):
            needs_order, amount = False, 0
        else:
            needs_order, amount = True, payment.amount
    if not needs_order:
        if notify:  # order already exists (e.g. a retried job): still make sure the agent hears back
            with session_scope() as session:
                enqueue_callback(session, request_id)
            jobs.kick()
        return
    # The PayTrust request_id is the Razorpay receipt, so a retry after a lost response is traceable.
    order = razorpay.create_order(request_id, amount, {"paytrust_request_id": request_id})
    _store_order(request_id, order, "ORDER_CREATED", notify)


# ── ai.investigate ──

@jobs.handler(AI_INVESTIGATE, max_attempts=lambda: 3)
def investigate(job: JobContext) -> None:
    from app.services import ai
    from app.services.evaluation import facts_for, summary

    request_id = job.payload["request_id"]
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        if payment is None or payment.ai is not None:
            return
        facts = facts_for(session, payment)
    result = ai.get_investigator().investigate(facts)  # falls back to a deterministic explanation
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id).with_for_update())
        if payment.ai is None:
            payment.ai = result
        updated = summary(payment)
    bus.publish("payment.updated", updated)


# ── callback.notify ──

def _callback_dead(job: JobContext, error: str, permanent: bool) -> None:
    from app.services.callbacks import callback_target

    with session_scope() as session:
        target = callback_target(session, job.payload["request_id"])
        audit.record(session, "system", "CALLBACK_BLOCKED" if permanent else "CALLBACK_FAILED",
                     job.payload["request_id"], url=target, attempts=job.attempt, detail=error[:300])


@jobs.handler(CALLBACK_NOTIFY, max_attempts=lambda: get_settings().CALLBACK_MAX_ATTEMPTS, on_dead=_callback_dead)
def notify(job: JobContext) -> None:
    from app.services.callbacks import deliver

    deliver(job.payload["request_id"], attempt=job.attempt)
