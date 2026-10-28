"""Domain errors → one consistent HTTP error body: {"error": {"code", "message", "details"?}}."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"

    def __init__(self, message: str, retry_after: int):
        super().__init__(message, {"retry_after": retry_after})
        self.retry_after = retry_after


class ServiceUnavailable(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
