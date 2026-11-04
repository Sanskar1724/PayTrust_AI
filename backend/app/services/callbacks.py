"""Signed outbound callbacks: tell the agent when a pending payment is resolved.

Header `X-PayTrust-Signature` = HMAC-SHA256(agent.webhook_secret, raw body), hex.

Every attempt re-resolves the host and connects to a vetted public IP (see netguard), and
redirects are never followed, so a callback cannot be turned against internal services.

Delivery runs as a `callback.notify` job: one attempt per run, retried with backoff by the
job system (services/jobs.py) and dead-lettered after CALLBACK_MAX_ATTEMPTS.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.log import get_logger
from app.models import Agent, Payment
from app.services import audit
from app.services.jobs import PermanentFailure
from app.services.netguard import UnsafeUrl, pin_public_address
from app.services.security import sign_payload

logger = get_logger("callbacks")


class DeliveryFailed(Exception):
    """The agent's server did not accept the callback; the job system retries."""


def callback_target(session: Session, request_id: str) -> str | None:
    payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
    if payment is None:
        return None
    agent = session.get(Agent, payment.agent_id)
    return payment.callback_url or (agent.callback_url if agent else None)


def deliver(request_id: str, attempt: int = 1) -> str:
    """One delivery attempt. Returns "delivered" or "skipped" (no callback URL configured);
    raises DeliveryFailed to retry, PermanentFailure if the URL is unsafe."""
    s = get_settings()
    with session_scope() as session:
        payment = session.scalar(select(Payment).where(Payment.request_id == request_id))
        if payment is None:
            return "skipped"
        agent = session.get(Agent, payment.agent_id)
        url = payment.callback_url or (agent.callback_url if agent else None)
        if not url or agent is None:
            return "skipped"
        body: dict[str, Any] = {
            "event": "payment.resolved",
            "request_id": payment.request_id,
            "status": payment.status,
            "decision": payment.decision,
            "order": payment.order,
            "reviewed_at": payment.reviewed_at.isoformat() if payment.reviewed_at else None,
        }
        secret = agent.webhook_secret

    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-PayTrust-Signature": sign_payload(secret, raw)}
    try:
        target = pin_public_address(url)
    except UnsafeUrl as exc:
        logger.warning(f"Callback {request_id} blocked: {exc}")
        raise PermanentFailure(str(exc)) from exc
    try:
        with httpx.Client(timeout=s.CALLBACK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = client.post(
                target.url,
                content=raw,
                headers=headers | {"Host": target.host_header},
                extensions={"sni_hostname": target.host},  # TLS + cert check against the real host name
            )
    except httpx.HTTPError as exc:
        raise DeliveryFailed(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    if resp.status_code >= 300:
        raise DeliveryFailed(f"agent server answered HTTP {resp.status_code}")

    with session_scope() as session:
        audit.record(session, "system", "CALLBACK_DELIVERED", request_id, url=url, attempts=attempt)
    return "delivered"
