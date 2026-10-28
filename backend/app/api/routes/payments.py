"""Payments: agents submit and poll; operators list, review and investigate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import AgentPrincipal, agent_or_operator, current_operator, require_agent, require_role
from app.db import get_session
from app.errors import NotFound
from app.models import Operator, Payment, Role
from app.schemas import Page, PaymentIn, PaymentOut, PaymentSummary, PlaygroundIn, ReviewIn
from app.services import approvals, evaluation

router = APIRouter(prefix="/v1", tags=["payments"])


def _out(payment: Payment, duplicate: bool = False) -> PaymentOut:
    out = PaymentOut.model_validate(payment)
    out.duplicate = duplicate
    return out


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=201,
    summary="Evaluate a payment (agents)",
    description=(
        "Runs Policy → Risk → Decision for one payment the agent wants to make. "
        "`decision` is ALLOW (proceed), ASK_USER (wait — status PENDING_APPROVAL until a human reviews it) "
        "or DENY. Retrying with the same `request_id` and body returns the stored decision with HTTP 200."
    ),
    responses={200: {"description": "Idempotent replay of an existing decision"},
               409: {"description": "request_id reused with a different body"}},
)
def create_payment(body: PaymentIn, response: Response, agent: AgentPrincipal = Depends(require_agent)):
    payment, created = evaluation.evaluate_payment(body, key_agent_id=agent.agent_id, source=agent.source,
                                                   actor=agent.actor)
    if not created:
        response.status_code = 200
    return _out(payment, duplicate=not created)


@router.post("/evaluate", response_model=PaymentOut, status_code=201, include_in_schema=False)
def create_payment_legacy(body: PaymentIn, response: Response, agent: AgentPrincipal = Depends(require_agent)):
    """v1 path kept for existing integrations."""
    return create_payment(body, response, agent)


@router.post("/playground/evaluate", response_model=PaymentOut, status_code=201,
             summary="Evaluate a payment as a chosen agent (operators)")
def playground(body: PlaygroundIn, response: Response, operator: Operator = Depends(require_role(Role.REVIEWER))):
    payment, created = evaluation.evaluate_payment(body, key_agent_id=None, source="playground",
                                                   actor=f"operator:{operator.email}")
    if not created:
        response.status_code = 200
    return _out(payment, duplicate=not created)


@router.get("/payments/{request_id}", response_model=PaymentOut, summary="Get one payment with full evidence")
def get_payment(request_id: str, principal=Depends(agent_or_operator), session: Session = Depends(get_session)):
    payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
    # Agents may only see their own payments; don't reveal that others exist.
    if payment is None or (isinstance(principal, AgentPrincipal) and payment.agent_id != principal.agent_id):
        raise NotFound(f"Payment '{request_id}' not found")
    return _out(payment)


@router.get("/payments", response_model=Page, summary="List payments (operators)")
def list_payments(
    status: str | None = None,
    decision: str | None = None,
    user_id: int | None = None,
    agent_id: int | None = None,
    source: str | None = None,
    include_arena: bool = Query(default=False, description="Include Agent Arena simulation traffic"),
    q: str | None = Query(default=None, max_length=100, description="Search request id or merchant"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Operator = Depends(current_operator),
    session: Session = Depends(get_session),
):
    stmt = select(Payment)
    if status:
        stmt = stmt.where(Payment.status == status.upper())
    if decision:
        stmt = stmt.where(Payment.decision == decision.upper())
    if user_id:
        stmt = stmt.where(Payment.user_id == user_id)
    if agent_id:
        stmt = stmt.where(Payment.agent_id == agent_id)
    if source:
        stmt = stmt.where(Payment.source == source)
    elif not include_arena:
        stmt = stmt.where(Payment.source != "arena")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Payment.request_id.ilike(like), Payment.merchant_name.ilike(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=[PaymentSummary.model_validate(r) for r in rows], total=total or 0, limit=limit, offset=offset)


@router.post("/payments/{request_id}/approve", response_model=PaymentOut, summary="Approve a pending payment")
def approve(request_id: str, body: ReviewIn | None = None, operator: Operator = Depends(require_role(Role.REVIEWER))):
    return _out(approvals.review(request_id, True, operator.email, body.note if body else None))


@router.post("/payments/{request_id}/reject", response_model=PaymentOut, summary="Reject a pending payment")
def reject(request_id: str, body: ReviewIn | None = None, operator: Operator = Depends(require_role(Role.REVIEWER))):
    return _out(approvals.review(request_id, False, operator.email, body.note if body else None))


@router.post("/payments/{request_id}/investigate", response_model=PaymentOut,
             summary="Run the advisory AI investigation now")
def investigate(request_id: str, operator: Operator = Depends(require_role(Role.REVIEWER))):
    return _out(evaluation.investigate_now(request_id, f"operator:{operator.email}"))
