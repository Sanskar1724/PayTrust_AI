"""api/security.py — Auth + observability for the PayTrust AI HTTP service.

- API-key auth via `X-API-Key` header (MVP: env `PAYTRUST_API_KEY`; dev fallback
  derived deterministically from `SECRET_KEY` so local runs always work).
- In-process sliding-window rate limiter (no Redis needed on a single instance).
- Request-id middleware: `X-Request-ID` in → response header + structured logs.

All checks are constant-time-ish (hash-then-compare) and never log the key.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from typing import Callable

from fastapi import Header, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import get_settings
from core.logger import get_logger, get_request_id, new_request_id, set_request_id

logger = get_logger("api.security")
settings = get_settings()

__all__ = [
    "api_key_for",
    "api_key_dependency",
    "RequestIdMiddleware",
    "InMemoryRateLimiter",
]


def api_key_for(settings_obj=None) -> str:
    """Effective API key for this environment (env override or deterministic dev key)."""
    s = settings_obj or settings
    if s.PAYTRUST_API_KEY:
        return s.PAYTRUST_API_KEY
    # Deterministic per-environment dev key — never committed, derived from SECRET_KEY.
    return f"dev-{hashlib.sha256(s.SECRET_KEY.encode()).hexdigest()[:16]}"


def _constant_eq(a: str, b: str) -> bool:
    """Compare digests (never compare raw secrets for logging)."""
    return hashlib.sha256(a.encode("utf-8")).hexdigest() == hashlib.sha256(b.encode("utf-8")).hexdigest()


class InMemoryRateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string (e.g. API key)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                return False, retry
            q.append(now)
            return True, 0


_rate_limiter = InMemoryRateLimiter(settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_WINDOW)


def api_key_dependency(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """Require a valid API key AND apply rate limiting for that key."""
    expected = api_key_for()
    if not x_api_key or not _constant_eq(expected, x_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key")
    allowed, retry = _rate_limiter.allow(x_api_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this API key",
            headers={"Retry-After": str(retry)},
        )
    # Log only the key fingerprint, never the key itself.
    fp = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()[:12]
    logger.debug(f"Authenticated api_key={fp} path={request.url.path}")
    return x_api_key


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Correlate a request across logs + response via X-Request-ID."""

    async def dispatch(self, request: Request, call_next: Callable):
        rid = request.headers.get("X-Request-ID")
        if rid:
            set_request_id(rid[:64])
        else:
            new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = get_request_id()
        return response