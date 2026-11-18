"""PayTrust: payment authorization for AI agents. Ask before every payment; pay only on `can_pay`."""
from paytrust.client import PayTrust, new_request_id, parse_callback, verify_callback
from paytrust.errors import (
    ApprovalTimeout,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    NotFound,
    PayTrustError,
    PermissionDenied,
    RateLimitError,
    ServerError,
    ValidationError,
)
from paytrust.models import Decision

__version__ = "0.1.0"
__all__ = [
    "PayTrust", "Decision", "new_request_id", "verify_callback", "parse_callback",
    "PayTrustError", "AuthenticationError", "PermissionDenied", "NotFound", "ConflictError", "ValidationError",
    "RateLimitError", "ServerError", "ConnectionError", "ApprovalTimeout",
]
