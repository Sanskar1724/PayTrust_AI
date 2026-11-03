"""Signed outbound callbacks: tell the agent when a pending payment is resolved.

Header `X-PayTrust-Signature` = HMAC-SHA256(agent.webhook_secret, raw body), hex.

Every attempt re-resolves the host and connects to a vetted public IP (see netguard), and
redirects are never followed, so a callback cannot be turned against internal services.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import get_settings
from app.db import session_scope
from app.log import get_logger
from app.models import Agent, Payment
from app.services import audit
from app.services.netguard import UnsafeUrl, pin_public_address
from app.services.security import sign_payload

logger = get_logger("callbacks")


def notify_agent(request_id: str) -> None:
    s = get_settings()
    with session_scope() as session:
        payment = session.query(Payment).filter_by(request_id=request_id).one_or_none()
        if payment is None:
            return
        agent = session.get(Agent, payment.agent_id)
        url = payment.callback_url or (agent.callback_url if agent else None)
        if not url or agent is None:
            return
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
    outcome, detail = "failed", None
    for attempt in range(1, s.CALLBACK_MAX_ATTEMPTS + 1):
        try:
            target = pin_public_address(url)
        except UnsafeUrl as exc:
            outcome, detail = "blocked", str(exc)
            logger.warning(f"Callback {request_id} blocked: {exc}")
            break
        try:
            with httpx.Client(timeout=s.CALLBACK_TIMEOUT_SECONDS, follow_redirects=False) as client:
                resp = client.post(
                    target.url,
                    content=raw,
                    headers=headers | {"Host": target.host_header},
                    extensions={"sni_hostname": target.host},  # TLS + cert check against the real host name
                )
            if resp.status_code < 300:
                outcome = "delivered"
                break
            detail = f"HTTP {resp.status_code}"
            logger.warning(f"Callback {request_id} attempt {attempt} got HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            detail = str(exc)[:200]
            logger.warning(f"Callback {request_id} attempt {attempt} failed: {exc}")
        if attempt < s.CALLBACK_MAX_ATTEMPTS:
            time.sleep(min(2 ** attempt, 10))

    with session_scope() as session:
        audit.record(session, "system", "CALLBACK_" + outcome.upper(), request_id, url=url, attempts=attempt,
                     detail=detail)
