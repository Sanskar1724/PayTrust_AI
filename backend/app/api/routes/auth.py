"""Operator sign-in and operator management."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import _enforce_rate_limit, current_operator, require_role
from app.db import get_session, utcnow
from app.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.models import Operator, Role
from app.schemas import LoginIn, OperatorIn, OperatorOut, TokenOut
from app.services import audit
from app.services.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/v1", tags=["auth"])
# Constant-time-ish path for unknown emails, so response timing doesn't reveal accounts.
_DUMMY_HASH = hash_password("timing-equalizer")


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, session: Session = Depends(get_session)):
    email = body.email.lower()
    _enforce_rate_limit(f"login:{email}")
    operator = session.scalar(select(Operator).where(Operator.email == email))
    valid = verify_password(body.password, operator.password_hash if operator else _DUMMY_HASH)
    if operator is None or not valid or not operator.is_active:
        raise Unauthorized("Incorrect email or password")
    operator.last_login_at = utcnow()
    audit.record(session, operator.email, "OPERATOR_LOGIN", None)
    return TokenOut(access_token=create_access_token(operator.id, operator.role),
                    operator=OperatorOut.model_validate(operator))


@router.get("/auth/me", response_model=OperatorOut)
def me(operator: Operator = Depends(current_operator)):
    return operator


@router.get("/operators", response_model=list[OperatorOut], tags=["operators"])
def list_operators(_: Operator = Depends(require_role(Role.ADMIN)), session: Session = Depends(get_session)):
    return session.scalars(select(Operator).order_by(Operator.id)).all()


@router.post("/operators", response_model=OperatorOut, status_code=201, tags=["operators"])
def create_operator(body: OperatorIn, admin: Operator = Depends(require_role(Role.ADMIN)),
                    session: Session = Depends(get_session)):
    operator = Operator(email=body.email.lower(), name=body.name, role=body.role,
                        password_hash=hash_password(body.password))
    session.add(operator)
    try:
        session.flush()
    except IntegrityError as exc:
        raise Conflict("An operator with this email already exists") from exc
    audit.record(session, admin.email, "OPERATOR_CREATED", None, email=operator.email, role=operator.role)
    return operator


class OperatorPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.patch("/operators/{operator_id}", response_model=OperatorOut, tags=["operators"])
def update_operator(operator_id: int, body: OperatorPatch, admin: Operator = Depends(require_role(Role.ADMIN)),
                    session: Session = Depends(get_session)):
    operator = session.get(Operator, operator_id)
    if operator is None:
        raise NotFound("Operator not found")
    if body.role is not None:
        if body.role not in Role.ALL:
            raise ValidationFailed(f"role must be one of {Role.ALL}")
        operator.role = body.role
    if body.is_active is not None:
        if operator.id == admin.id and not body.is_active:
            raise ValidationFailed("You cannot deactivate yourself")
        operator.is_active = body.is_active
    if body.password:
        if len(body.password) < 8:
            raise ValidationFailed("password must be at least 8 characters")
        operator.password_hash = hash_password(body.password)
    audit.record(session, admin.email, "OPERATOR_UPDATED", None, operator_id=operator_id,
                 role=body.role, is_active=body.is_active, password_changed=bool(body.password))
    return operator
