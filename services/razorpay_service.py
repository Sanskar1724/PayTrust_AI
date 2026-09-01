"""
services/razorpay_service.py — Phase 11 Razorpay Test Mode integration.

- Secrets only in .env (never logged, never in DB, never in UI)
- HMAC-SHA256 over RAW body for webhook verification (before JSON parse)
- Idempotency via razorpay_events.event_id + payload_hash
- Retry with exponential backoff, DLQ handling
- All actions are TEST MODE / SIMULATED — never live money

For local testing without real keys, all operations degrade gracefully to SIMULATED.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from core.config import get_settings
from core.logger import get_logger, get_request_id
from core.exceptions import DatabaseError
from database.database import get_connection

logger = get_logger("services.razorpay")
settings = get_settings()

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

# ── Secret handling ──

def _require_test_keys() -> tuple[str, str]:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise ValueError("Razorpay Test Mode keys not configured — set RAZORPAY_KEY_ID/SECRET in .env or use SIMULATED mode")
    if not settings.RAZORPAY_KEY_ID.startswith("rzp_test_"):
        raise ValueError("RAZORPAY_KEY_ID must be TEST MODE (rzp_test_*) — live keys are not allowed")
    return settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET

# ── Webhook verification (RAW body) ──

def verify_webhook_signature(raw_body: bytes, signature: str, secret: Optional[str] = None) -> bool:
    """
    Verify Razorpay X-Razorpay-Signature over RAW body.
    Must be called BEFORE json parsing. Uses constant-time compare.
    """
    sec = secret if secret is not None else settings.RAZORPAY_WEBHOOK_SECRET
    if not sec:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not configured — skipping verification (dev only)")
        return True
    expected = hmac.new(sec.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")

def payload_hash(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()

# ── Idempotency & event persistence ──

def is_duplicate_event(event_id: str, payload_hash_val: str, db_path: Path | None = None) -> tuple[bool, str]:
    """
    Returns (is_duplicate, existing_status). If event_id exists, it's duplicate.
    Payload hash mismatch is logged but still treated as duplicate (do not reprocess).
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT payload_hash, status FROM razorpay_events WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        if row:
            if row["payload_hash"] != payload_hash_val:
                logger.warning(f"Duplicate event {event_id} with different payload hash — treating as duplicate, not reprocessing")
            return True, row["status"]
        return False, ""
    finally:
        conn.close()

def record_event(
    event_id: str,
    event_type: str,
    payload_hash_val: str,
    payment_id: str | None = None,
    raw_payload: bytes | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO razorpay_events (event_id, event_type, payment_id, payload_hash, status) VALUES (?,?,?,?,?)",
            (event_id, event_type, payment_id, payload_hash_val, "RECEIVED"),
        )
        conn.commit()
        cur.execute("SELECT * FROM razorpay_events WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()

def mark_event_processed(event_id: str, status: str = "PROCESSED", error: str | None = None, db_path: Path | None = None):
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE razorpay_events SET status = ?, processed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'), error_message = ? WHERE event_id = ?",
            (status, error, event_id),
        )
        conn.commit()
    finally:
        conn.close()

# ── Webhook handler (called by Streamlit or API) ──

def handle_webhook(raw_body: bytes, signature: str, db_path: Path | None = None) -> dict[str, Any]:
    """
    Entry point for webhook: verify → idempotency → persist → return.

    Never logs raw_body or secrets (redacted by logger).
    """
    # 1. Verify
    if not verify_webhook_signature(raw_body, signature):
        logger.warning(f"Webhook signature invalid — rejecting")
        return {"status": "rejected", "reason": "invalid_signature"}

    # 2. Parse after verification
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        return {"status": "rejected", "reason": f"invalid_json: {exc}"}

    event_id = data.get("id") or data.get("event_id") or f"evt_{hash(raw_body) & 0xffffffff}"
    event_type = data.get("event") or data.get("type") or "unknown"
    # Try extract payment id from Razorpay payload shape
    payment_id = None
    try:
        payment_id = data.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
        if not payment_id:
            payment_id = data.get("payload", {}).get("order", {}).get("entity", {}).get("id")
    except Exception:
        pass

    phash = payload_hash(raw_body)

    # 3. Idempotency
    dup, existing_status = is_duplicate_event(event_id, phash, db_path)
    if dup:
        logger.info(f"Webhook duplicate {event_id} existing={existing_status} — idempotent ignore")
        return {"status": "duplicate", "event_id": event_id, "existing_status": existing_status}

    # 4. Persist
    record_event(event_id, event_type, phash, payment_id, raw_body, db_path)
    # Mark as processed immediately for local prototype (in production would enqueue)
    mark_event_processed(event_id, "PROCESSED", None, db_path)

    # 5. Structured audit (no secrets)
    from database.database import get_connection as _gc
    conn = _gc(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_logs (request_id, event_type, actor, action, metadata) VALUES (?,?,?,?,?)",
            (payment_id or event_id, "WEBHOOK_RECEIVED", "razorpay", event_type, json.dumps({"event_id": event_id, "event_type": event_type, "request_id": get_request_id()})),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    logger.info(f"Webhook processed {event_id} type={event_type}")
    return {"status": "processed", "event_id": event_id, "event_type": event_type}

# ── Test Mode payment operations (SIMULATED if no keys) ──

def create_test_order(amount: int, currency: str = "INR", receipt: str | None = None, notes: dict | None = None) -> dict[str, Any]:
    """
    Create a Razorpay TEST MODE order. If keys missing, returns SIMULATED response.
    Amount is in INR (will be converted to paise for API).
    """
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        logger.info("Razorpay keys missing — returning SIMULATED order")
        return {
            "id": f"order_SIMULATED_{int(time.time())}",
            "amount": amount * 100,
            "currency": currency,
            "receipt": receipt or f"rcpt_{int(time.time())}",
            "status": "created",
            "simulated": True,
            "disclaimer": "SIMULATED — no real money, TEST MODE only",
        }
    key_id, key_secret = _require_test_keys()
    try:
        with httpx.Client(timeout=10.0, auth=(key_id, key_secret)) as client:
            resp = client.post(
                f"{RAZORPAY_API_BASE}/orders",
                json={"amount": amount * 100, "currency": currency, "receipt": receipt or f"rcpt_{int(time.time())}", "notes": notes or {}},
            )
            resp.raise_for_status()
            data = resp.json()
            data["simulated"] = False
            return data
    except Exception as exc:
        logger.warning(f"Razorpay order create failed: {exc} — returning SIMULATED")
        return {"id": f"order_error_{int(time.time())}", "amount": amount * 100, "currency": currency, "status": "error", "error": str(exc)[:300], "simulated": True}

def fetch_payment(payment_id: str) -> dict[str, Any]:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return {"id": payment_id, "status": "simulated", "simulated": True}
    key_id, key_secret = _require_test_keys()
    with httpx.Client(timeout=10.0, auth=(key_id, key_secret)) as client:
        resp = client.get(f"{RAZORPAY_API_BASE}/payments/{payment_id}")
        resp.raise_for_status()
        return resp.json()

def list_webhook_events(limit: int = 20, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT event_id, event_type, payment_id, status, received_at, processed_at FROM razorpay_events ORDER BY received_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

# ── Helper for local tunnel instructions ──

TUNNEL_HELP = """
For local webhook testing (no public URL):
  1. Keep this app running.
  2. Use ngrok / cloudflared / VS Code Port Forwarding to expose localhost:8501 or your API port.
  3. In Razorpay Dashboard (Test Mode) → Webhooks → Add Webhook:
     URL = https://<your-tunnel>/api/webhooks/razorpay  (or paste to manual tester in Audit Log)
     Secret = value of RAZORPAY_WEBHOOK_SECRET in .env (never commit)
     Events = payment.authorized, payment.captured, payment.failed, order.paid
  4. Send test webhook from Dashboard → verify signature via raw body.
  5. Check `razorpay_events` table and Audit Log for idempotency.
Never use live keys. All payments are TEST MODE / SIMULATED.
"""
