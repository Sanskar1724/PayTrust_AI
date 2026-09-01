"""
core/logger.py — Structured logging for PayTrust AI.

- Never logs secrets (API keys, webhook secrets).
- Adds request_id / event_type context when available.
- Uses stdlib logging with optional JSON formatting via python-json-logger.
"""
from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

# Per-request correlation id for Streamlit threads
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Patterns to redact
_REDACT_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(secret\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"sk-or-v1-[A-Za-z0-9\-_]+"),
    re.compile(r"rzp_test_[A-Za-z0-9]+"),
    re.compile(r"gsk_[A-Za-z0-9]+"),
]

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | req=%(request_id)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rid = _request_id_ctx.get()
        if rid is None:
            rid = "-"
        record.request_id = rid  # type: ignore[attr-defined]
        return True


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pat in _REDACT_PATTERNS:
            try:
                # Patterns with a capture group keep the prefix, others just replace
                if pat.groups >= 1:
                    msg = pat.sub(r"\1***REDACTED***", msg)
                else:
                    msg = pat.sub("***REDACTED***", msg)
            except Exception:
                # Fallback: simple replace without group reference
                try:
                    msg = pat.sub("***REDACTED***", msg)
                except Exception:
                    pass
        return msg


def get_request_id() -> str:
    """Get or create a request id for current context."""
    rid = _request_id_ctx.get()
    if rid is None:
        rid = uuid.uuid4().hex[:12]
        _request_id_ctx.set(rid)
    return rid


def set_request_id(rid: str | None) -> None:
    _request_id_ctx.set(rid)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _request_id_ctx.set(rid)
    return rid


def get_logger(name: str) -> logging.Logger:
    """Return a logger with redaction + request_id filter attached."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Only configure once — Streamlit re-runs should not duplicate handlers
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
        handler.addFilter(RequestIdFilter())
        logger.addHandler(handler)
        # Prevent double propagation to root
        logger.propagate = False
    return logger


def configure_root_logging(level: int = logging.INFO) -> None:
    """Call once at startup to configure root logger."""
    root = logging.getLogger()
    # Ensure root also has request_id field for records from libraries
    if not any(isinstance(f, RequestIdFilter) for f in root.filters):
        root.addFilter(RequestIdFilter())
    root.setLevel(level)
    # Configure paytrust loggers
    for name in ("paytrust", "app", "engines", "database", "services"):
        get_logger(name).setLevel(level)


def log_event(
    logger: logging.Logger,
    level: int,
    event_type: str,
    message: str,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Helper for structured event logging without secrets."""
    ctx = {
        "event_type": event_type,
        "request_id": get_request_id(),
    }
    if extra:
        ctx.update({k: v for k, v in extra.items() if "secret" not in k.lower() and "api_key" not in k.lower()})
    ctx.update(kwargs)
    logger.log(level, f"{event_type} | {message} | ctx={ctx}")
