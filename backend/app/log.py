"""Structured logging with request-id correlation and secret redaction."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(pt_[a-z0-9]{8}_)[A-Za-z0-9_\-]+"),            # PayTrust agent keys
    re.compile(r"(rzp_(?:test|live)_)[A-Za-z0-9]+"),              # Razorpay key ids
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),               # JWT / bearer tokens
    re.compile(r"(?i)((?:api[_-]?key|secret|password|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str | None = None) -> str:
    rid = (value or uuid.uuid4().hex)[:64]
    _request_id.set(rid)
    return rid


class _Formatter(logging.Formatter):
    def __init__(self, as_json: bool):
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        message = redact(record.getMessage())
        if record.exc_info:
            message += "\n" + redact(self.formatException(record.exc_info))
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")
        if self.as_json:
            return json.dumps({
                "ts": ts,
                "level": record.levelname,
                "logger": record.name,
                "request_id": get_request_id(),
                "msg": message,
            })
        return f"{ts} {record.levelname:<7} {record.name:<22} req={get_request_id()[:12]} {message}"


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(as_json))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"paytrust.{name}")
