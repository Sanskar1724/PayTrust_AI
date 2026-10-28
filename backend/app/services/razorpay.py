"""Razorpay integration: create an order once a payment is ALLOWED/APPROVED, ingest webhooks.

RAZORPAY_MODE:
  simulated — no network; deterministic fake order ids (default, safe for local dev)
  test      — real Razorpay API with rzp_test_* keys
  live      — real Razorpay API with rzp_live_* keys
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ServiceUnavailable, Unauthorized, ValidationFailed
from app.log import get_logger
from app.models import WebhookEvent
from app.services import audit

logger = get_logger("razorpay")
API_BASE = "https://api.razorpay.com/v1"
_EXPECTED_KEY_PREFIX = {"test": "rzp_test_", "live": "rzp_live_"}


def _credentials() -> tuple[str, str]:
    s = get_settings()
    if not s.RAZORPAY_KEY_ID or not s.RAZORPAY_KEY_SECRET:
        raise ServiceUnavailable("Razorpay keys are not configured")
    expected = _EXPECTED_KEY_PREFIX[s.RAZORPAY_MODE]
    if not s.RAZORPAY_KEY_ID.startswith(expected):
        raise ServiceUnavailable(f"RAZORPAY_MODE={s.RAZORPAY_MODE} requires a {expected}* key id")
    return s.RAZORPAY_KEY_ID, s.RAZORPAY_KEY_SECRET


def create_order(request_id: str, amount_inr: int, notes: dict[str, str] | None = None) -> dict[str, Any]:
    """Create (or simulate) an order. The PayTrust request_id is the receipt, so retries are traceable."""
    s = get_settings()
    if s.RAZORPAY_MODE == "simulated":
        digest = hashlib.sha256(request_id.encode()).hexdigest()[:14]
        return {
            "id": f"order_sim_{digest}",
            "amount": amount_inr * 100,
            "currency": "INR",
            "receipt": request_id,
            "status": "created",
            "mode": "simulated",
        }
    key_id, key_secret = _credentials()
    body = {"amount": amount_inr * 100, "currency": "INR", "receipt": request_id[:40], "notes": notes or {}}
    last_error = None
    for _ in range(3):
        try:
            with httpx.Client(timeout=10.0, auth=(key_id, key_secret)) as client:
                resp = client.post(f"{API_BASE}/orders", json=body)
            if resp.status_code >= 500 or resp.status_code == 429:
                last_error = f"HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            data = resp.json()
            return {k: data.get(k) for k in ("id", "amount", "currency", "receipt", "status")} | {"mode": s.RAZORPAY_MODE}
        except httpx.HTTPError as exc:
            last_error = str(exc)[:200]
    raise ServiceUnavailable(f"Razorpay order creation failed: {last_error}")


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    secret = get_settings().RAZORPAY_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def ingest_webhook(session: Session, raw_body: bytes, signature: str | None) -> dict[str, Any]:
    """Verify over the RAW body, then record idempotently. Duplicates return status=duplicate."""
    if not verify_signature(raw_body, signature):
        raise Unauthorized("Invalid or missing X-Razorpay-Signature")
    try:
        data = json.loads(raw_body)
    except ValueError as exc:
        raise ValidationFailed("Webhook body is not valid JSON") from exc

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    event_id = str(data.get("id") or payload_hash)
    event_type = str(data.get("event") or "unknown")
    entity = None
    for kind in ("payment", "order", "refund"):
        entity = ((data.get("payload") or {}).get(kind) or {}).get("entity", {}).get("id")
        if entity:
            break

    if session.scalar(select(WebhookEvent.id).where(WebhookEvent.event_id == event_id)):
        return {"status": "duplicate", "event_id": event_id}
    try:
        with session.begin_nested():
            session.add(WebhookEvent(event_id=event_id, event_type=event_type, entity_id=entity, payload_hash=payload_hash))
    except IntegrityError:  # concurrent delivery of the same event
        return {"status": "duplicate", "event_id": event_id}
    audit.record(session, "razorpay", "WEBHOOK_RECEIVED", None, event_id=event_id, webhook_event=event_type,
                 entity_id=entity)
    logger.info(f"Webhook {event_type} {event_id} recorded")
    return {"status": "processed", "event_id": event_id, "event_type": event_type}
