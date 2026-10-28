"""Authentication + authorization dependencies.

Each check uses its own short transaction, so no lock or pooled connection is held
while the route runs (on SQLite a held write lock would block the route's own work).

Agents authenticate with `X-API-Key: pt_<prefix>_<secret>`.
Operators authenticate with `Authorization: Bearer <jwt>` from /v1/auth/login.
Both are rate limited per principal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.errors import Forbidden, RateLimited, Unauthorized
from app.models import Agent, ApiKey, Operator, Role
from app.services.ratelimit import RateLimiter
from app.services.security import api_key_matches, decode_access_token, parse_api_key

ARENA_KEY_PREFIX = "arena-"  # keys minted by the Agent Arena; their traffic is tagged source=arena
_limiter: RateLimiter | None = None


def limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = RateLimiter(s.RATE_LIMIT_REQUESTS, s.RATE_LIMIT_WINDOW_SECONDS, s.REDIS_URL)
    return _limiter


def reset_limiter() -> None:
    global _limiter
    _limiter = None


def _enforce_rate_limit(key: str) -> None:
    allowed, retry_after = limiter().hit(key)
    if not allowed:
        raise RateLimited("Too many requests", retry_after)


@dataclass(frozen=True)
class AgentPrincipal:
    agent_id: int
    key_id: int
    key_prefix: str
    key_name: str = ""

    @property
    def source(self) -> str:
        return "arena" if self.key_name.startswith(ARENA_KEY_PREFIX) else "api"

    @property
    def actor(self) -> str:
        return f"agent:{self.agent_id}/key:{self.key_prefix}"


def authenticate_agent(session: Session, raw_key: str | None) -> AgentPrincipal | None:
    if not raw_key:
        return None
    parsed = parse_api_key(raw_key.strip())
    if parsed is None:
        return None
    prefix, secret = parsed
    key = session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if key is None or key.revoked_at is not None or not api_key_matches(secret, key.key_hash):
        return None
    agent = session.get(Agent, key.agent_id)
    if agent is None or not agent.is_active:
        return None
    now = utcnow()
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
    return AgentPrincipal(agent_id=key.agent_id, key_id=key.id, key_prefix=prefix, key_name=key.name)


def authenticate_operator(session: Session, token: str | None) -> Operator | None:
    if not token:
        return None
    claims = decode_access_token(token)
    if claims is None:
        return None
    operator = session.get(Operator, int(claims["sub"]))
    if operator is None or not operator.is_active:
        return None
    return operator


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _agent(raw_key: str | None) -> AgentPrincipal | None:
    if not raw_key:
        return None
    with session_scope() as session:
        return authenticate_agent(session, raw_key)


def _operator(token: str | None) -> Operator | None:
    if not token:
        return None
    with session_scope() as session:
        return authenticate_operator(session, token)


def require_agent(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> AgentPrincipal:
    principal = _agent(x_api_key)
    if principal is None:
        raise Unauthorized("Missing or invalid X-API-Key")
    _enforce_rate_limit(f"key:{principal.key_prefix}")
    return principal


def current_operator(authorization: str | None = Header(default=None)) -> Operator:
    operator = _operator(_bearer(authorization))
    if operator is None:
        raise Unauthorized("Sign in required")
    _enforce_rate_limit(f"op:{operator.id}")
    return operator


def require_role(minimum: str):
    def _check(operator: Operator = Depends(current_operator)) -> Operator:
        if Role.RANK.get(operator.role, -1) < Role.RANK[minimum]:
            raise Forbidden(f"Requires the {minimum} role")
        return operator

    return _check


def agent_or_operator(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> AgentPrincipal | Operator:
    principal = _agent(x_api_key)
    if principal is not None:
        _enforce_rate_limit(f"key:{principal.key_prefix}")
        return principal
    operator = _operator(_bearer(authorization))
    if operator is not None:
        _enforce_rate_limit(f"op:{operator.id}")
        return operator
    raise Unauthorized("Provide X-API-Key (agents) or a bearer token (operators)")


def operator_from_query_token(
    token: str | None = Query(default=None, description="Bearer token (EventSource cannot send headers)"),
) -> Operator:
    operator = _operator(token)  # a stream must not pin a pooled connection for hours
    if operator is None:
        raise Unauthorized("Sign in required")
    return operator
