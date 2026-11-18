"""Errors raised by the PayTrust client. All inherit from PayTrustError."""
from __future__ import annotations

from typing import Any


class PayTrustError(Exception):
    """An error response from PayTrust, or a request that could not be completed."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 details: Any = None, trace_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details
        self.trace_id = trace_id  # PayTrust's X-Request-ID: quote it when reporting a problem

    def __str__(self) -> str:
        parts = [self.message]
        if self.status:
            parts.insert(0, f"HTTP {self.status}")
        if self.trace_id:
            parts.append(f"(trace {self.trace_id})")
        return " ".join(parts)


class AuthenticationError(PayTrustError):
    """401: the API key is missing, malformed, revoked, or the agent is disabled."""


class PermissionDenied(PayTrustError):
    """403: the credentials are valid but not allowed to do this."""


class NotFound(PayTrustError):
    """404: e.g. a payment that does not exist or belongs to another agent."""


class ConflictError(PayTrustError):
    """409: e.g. a request_id reused with a different payment."""


class ValidationError(PayTrustError):
    """422: the request was rejected before evaluation (see `details` for the fields)."""


class RateLimitError(PayTrustError):
    """429: too many requests. `retry_after` is in seconds."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ServerError(PayTrustError):
    """5xx: PayTrust could not decide. Fail closed: do not pay."""


class ConnectionError(PayTrustError):  # noqa: A001 (deliberately shadows the builtin inside this package)
    """PayTrust could not be reached. Fail closed: do not pay."""


class ApprovalTimeout(PayTrustError):
    """wait_for_resolution gave up while the payment was still waiting for a human."""


STATUS_ERRORS: dict[int, type[PayTrustError]] = {
    401: AuthenticationError, 403: PermissionDenied, 404: NotFound, 409: ConflictError, 422: ValidationError,
}
