"""Users (payers), agents + API keys, merchants and policies."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_operator, require_role
from app.db import get_session, utcnow
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import Agent, ApiKey, Merchant, Operator, Policy, Role, User
from app.schemas import (
    AgentCreated,
    AgentIn,
    AgentOut,
    AgentPatch,
    ApiKeyCreated,
    ApiKeyIn,
    MerchantIn,
    MerchantOut,
    PolicyIn,
    PolicyOut,
    UserIn,
    UserOut,
)
from app.services import audit
from app.services.security import generate_api_key, new_webhook_secret

router = APIRouter(prefix="/v1", tags=["directory"])
admin = require_role(Role.ADMIN)


def _flush(session: Session, what: str) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(f"{what} already exists") from exc


# ── Users ──

@router.get("/users", response_model=list[UserOut])
def list_users(include_arena: bool = False, _: Operator = Depends(current_operator),
               session: Session = Depends(get_session)):
    stmt = select(User).order_by(User.id)
    if not include_arena:
        stmt = stmt.where(or_(User.external_ref.is_(None), ~User.external_ref.startswith("arena:")))
    return session.scalars(stmt).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, op: Operator = Depends(admin), session: Session = Depends(get_session)):
    user = User(**body.model_dump())
    session.add(user)
    _flush(session, "A user with this external_ref")
    audit.record(session, op.email, "USER_CREATED", None, user_id=user.id)
    return user


# ── Agents + keys ──

@router.get("/agents", response_model=list[AgentOut])
def list_agents(_: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return session.scalars(select(Agent).options(selectinload(Agent.keys)).order_by(Agent.id)).all()


@router.post("/agents", response_model=AgentCreated, status_code=201)
def create_agent(body: AgentIn, op: Operator = Depends(admin), session: Session = Depends(get_session)):
    agent = Agent(**body.model_dump(), webhook_secret=new_webhook_secret())
    session.add(agent)
    _flush(session, "An agent with this name")
    audit.record(session, op.email, "AGENT_CREATED", None, agent_id=agent.id)
    return AgentCreated.model_validate({**AgentOut.model_validate(agent).model_dump(),
                                        "webhook_secret": agent.webhook_secret})


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, body: AgentPatch, op: Operator = Depends(admin),
                 session: Session = Depends(get_session)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise NotFound("Agent not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(agent, field, value)
    audit.record(session, op.email, "AGENT_UPDATED", None, agent_id=agent_id, changes=changes)
    session.flush()
    session.refresh(agent)
    return agent


@router.post("/agents/{agent_id}/keys", response_model=ApiKeyCreated, status_code=201)
def create_key(agent_id: int, body: ApiKeyIn | None = None, op: Operator = Depends(admin),
               session: Session = Depends(get_session)):
    if session.get(Agent, agent_id) is None:
        raise NotFound("Agent not found")
    full_key, prefix, digest = generate_api_key()
    key = ApiKey(agent_id=agent_id, name=(body.name if body else "default"), prefix=prefix, key_hash=digest)
    session.add(key)
    session.flush()
    audit.record(session, op.email, "API_KEY_CREATED", None, agent_id=agent_id, key_prefix=prefix)
    return ApiKeyCreated(id=key.id, name=key.name, prefix=prefix, created_at=key.created_at,
                         last_used_at=None, revoked_at=None, key=full_key)


@router.delete("/agents/{agent_id}/keys/{key_id}", status_code=204)
def revoke_key(agent_id: int, key_id: int, op: Operator = Depends(admin), session: Session = Depends(get_session)):
    key = session.get(ApiKey, key_id)
    if key is None or key.agent_id != agent_id:
        raise NotFound("API key not found")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit.record(session, op.email, "API_KEY_REVOKED", None, agent_id=agent_id, key_prefix=key.prefix)


# ── Merchants ──

@router.get("/merchants", response_model=list[MerchantOut])
def list_merchants(_: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return session.scalars(select(Merchant).order_by(Merchant.id)).all()


@router.post("/merchants", response_model=MerchantOut, status_code=201)
def create_merchant(body: MerchantIn, op: Operator = Depends(admin), session: Session = Depends(get_session)):
    merchant = Merchant(**body.model_dump())
    session.add(merchant)
    session.flush()
    audit.record(session, op.email, "MERCHANT_CREATED", None, merchant_id=merchant.id)
    return merchant


@router.put("/merchants/{merchant_id}", response_model=MerchantOut)
def update_merchant(merchant_id: int, body: MerchantIn, op: Operator = Depends(admin),
                    session: Session = Depends(get_session)):
    merchant = session.get(Merchant, merchant_id)
    if merchant is None:
        raise NotFound("Merchant not found")
    for field, value in body.model_dump().items():
        setattr(merchant, field, value)
    audit.record(session, op.email, "MERCHANT_UPDATED", None, merchant_id=merchant_id, **body.model_dump())
    return merchant


# ── Policies ──

@router.get("/policies", response_model=list[PolicyOut])
def list_policies(_: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    return session.scalars(select(Policy).order_by(Policy.user_id, Policy.agent_id)).all()


@router.put("/policies", response_model=PolicyOut, summary="Create or replace the policy for a user + agent")
def upsert_policy(body: PolicyIn, op: Operator = Depends(admin), session: Session = Depends(get_session)):
    if session.get(User, body.user_id) is None:
        raise ValidationFailed(f"User {body.user_id} does not exist")
    if session.get(Agent, body.agent_id) is None:
        raise ValidationFailed(f"Agent {body.agent_id} does not exist")
    policy = session.scalar(select(Policy).where(Policy.user_id == body.user_id, Policy.agent_id == body.agent_id))
    before = policy.as_rules() if policy else None
    if policy is None:
        policy = Policy(user_id=body.user_id, agent_id=body.agent_id)
        session.add(policy)
    for field, value in body.model_dump(exclude={"user_id", "agent_id"}).items():
        setattr(policy, field, value)
    policy.updated_by = op.email
    session.flush()
    audit.record(session, op.email, "POLICY_UPDATED", None, user_id=body.user_id, agent_id=body.agent_id,
                 before=before, after=policy.as_rules())
    return policy
