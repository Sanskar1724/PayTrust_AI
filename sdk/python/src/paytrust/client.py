"""PayTrust API client for AI agents.

    from paytrust import PayTrust

    pt = PayTrust(api_key="pt_…", base_url="https://paytrust.example.com")
    d = pt.authorize(user_id=1, merchant_id=7, merchant_name="TechMart Electronics",
                     amount=2_999, category="electronics", description="Wireless earbuds",
                     reason="User asked for earbuds under ₹3,500")
    if d.waiting_for_approval:
        d = pt.wait_for_resolution(d.request_id)
    if d.can_pay:
        ...  # pay, using d.order
    else:
        tell_user(d.explain())

Retries are safe: every attempt of one authorize() call reuses the same request_id, and
PayTrust returns the stored decision instead of deciding (or paying) twice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from paytrust.errors import (
    STATUS_ERRORS,
    ApprovalTimeout,
    ConnectionError,
    PayTrustError,
    RateLimitError,
    ServerError,
)
from paytrust.models import Decision

DEFAULT_TIMEOUT = 15.0
RETRY_STATUSES = {429, 500, 502, 503, 504}


def new_request_id(prefix: str = "pt") -> str:
    """A fresh idempotency key. Prefer your own stable id (e.g. your order id) when you have one."""
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class PayTrust:
    """Synchronous client. `http_client` lets you pass a pre-configured httpx-compatible client."""

    def __init__(self, api_key: str, base_url: str = "http://127.0.0.1:8000", *, timeout: float = DEFAULT_TIMEOUT,
                 max_retries: int = 3, http_client: Any = None) -> None:
        if not api_key or not api_key.startswith("pt_"):
            raise ValueError("api_key must be a PayTrust agent key (starts with 'pt_')")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> PayTrust:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    # ── API ──

    def authorize(self, *, user_id: int, merchant_id: int, merchant_name: str, amount: int, category: str,
                  description: str | None = None, reason: str | None = None, request_id: str | None = None,
                  callback_url: str | None = None, agent_id: int | None = None) -> Decision:
        """Ask PayTrust before paying. `amount` is whole INR. Never pay unless `.can_pay`."""
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            raise ValueError("amount must be a positive whole number of INR")
        body: dict[str, Any] = {
            "request_id": request_id or new_request_id(),
            "user_id": user_id,
            "merchant_id": merchant_id,
            "merchant_name": merchant_name,
            "amount": amount,
            "category": category,
            "description": description,
            "agent_reason": reason,
            "callback_url": callback_url,
        }
        if agent_id is not None:
            body["agent_id"] = agent_id
        return Decision.from_response(self._request("POST", "/v1/payments", json=body))

    def get(self, request_id: str) -> Decision:
        """The payment's current state (an agent can only see its own payments)."""
        return Decision.from_response(self._request("GET", f"/v1/payments/{request_id}"))

    def wait_for_resolution(self, request_id: str, *, timeout: float = 900.0, poll_interval: float = 3.0) -> Decision:
        """Poll until a human approves or rejects the payment (or it expires).

        Raises ApprovalTimeout if it is still pending after `timeout` seconds. Prefer a
        callback_url in production; this is for simple agents and scripts."""
        deadline = time.monotonic() + timeout
        while True:
            decision = self.get(request_id)
            if decision.is_final:
                return decision
            if time.monotonic() >= deadline:
                raise ApprovalTimeout(f"Payment {request_id} is still waiting for approval after {timeout:g} s")
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    # ── transport ──

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-API-Key": self.api_key, "User-Agent": "paytrust-python/0.1"}
        attempt = 0
        while True:
            try:
                resp = self._http.request(method, path, json=json, headers=headers)
            except Exception as exc:  # transport failure: httpx or any compatible client
                if attempt >= self.max_retries or not _is_transport_error(exc):
                    raise ConnectionError(f"Could not reach PayTrust: {exc}") from exc
                attempt += 1
                time.sleep(_backoff(attempt))
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                attempt += 1
                time.sleep(_retry_after(resp) or _backoff(attempt))
                continue
            return _parse(resp)


def _is_transport_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return isinstance(exc, (httpx.TransportError, OSError)) or name.endswith(("TransportError", "ConnectError",
                                                                               "TimeoutException", "ReadTimeout"))


def _backoff(attempt: int) -> float:
    return min(0.5 * 2 ** (attempt - 1), 8.0)


def _retry_after(resp: Any) -> float | None:
    try:
        return float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def _parse(resp: Any) -> dict[str, Any]:
    trace = resp.headers.get("X-Request-ID")
    try:
        data = resp.json()
    except ValueError:
        data = None
    if 200 <= resp.status_code < 300 and isinstance(data, dict):
        return data
    err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
    message = err.get("message") or f"Unexpected response from PayTrust ({resp.status_code})"
    kw = {"status": resp.status_code, "code": err.get("code"), "details": err.get("details"), "trace_id": trace}
    if resp.status_code == 429:
        raise RateLimitError(message, retry_after=_retry_after(resp), **kw)
    if resp.status_code >= 500:
        raise ServerError(message, **kw)
    raise STATUS_ERRORS.get(resp.status_code, PayTrustError)(message, **kw)


def verify_callback(raw_body: bytes, signature: str | None, webhook_secret: str) -> bool:
    """True if `signature` (the X-PayTrust-Signature header) matches the RAW request body.

    Verify before trusting a callback: compute over the exact bytes received, not re-encoded JSON."""
    if not signature:
        return False
    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def parse_callback(raw_body: bytes, signature: str | None, webhook_secret: str) -> dict[str, Any]:
    """Verify and decode a PayTrust callback; raises PayTrustError if the signature is wrong."""
    if not verify_callback(raw_body, signature, webhook_secret):
        raise PayTrustError("Invalid X-PayTrust-Signature: do not trust this callback")
    return json.loads(raw_body)
