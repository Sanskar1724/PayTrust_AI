"""
core/exceptions.py — Structured exception hierarchy for PayTrust AI.

All engines/services should raise these instead of raw ValueError, so UI
and tests can distinguish user errors vs system failures without leaking secrets.
"""
from __future__ import annotations


class PayTrustError(Exception):
    """Base for all domain errors."""

    def __init__(self, message: str, *, code: str = "PAYTRUST_ERROR", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConfigurationError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="CONFIG_ERROR", **kwargs)


class ValidationError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="VALIDATION_ERROR", **kwargs)


class PolicyError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="POLICY_ERROR", **kwargs)


class RiskEngineError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="RISK_ENGINE_ERROR", **kwargs)


class DecisionEngineError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="DECISION_ERROR", **kwargs)


class DatabaseError(PayTrustError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="DATABASE_ERROR", **kwargs)


class AIProviderError(PayTrustError):
    def __init__(self, message: str, *, provider: str | None = None, **kwargs):
        super().__init__(message, code="AI_PROVIDER_ERROR", **kwargs)
        self.provider = provider


class PaymentValidationError(ValidationError):
    def __init__(self, message: str, *, field: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.field = field
        self.code = "PAYMENT_VALIDATION_ERROR"


class AuthenticationError(PayTrustError):
    def __init__(self, message: str = "Authentication required", **kwargs):
        super().__init__(message, code="AUTH_ERROR", **kwargs)


class AuthorizationError(PayTrustError):
    def __init__(self, message: str = "Insufficient permissions", **kwargs):
        super().__init__(message, code="AUTHORIZATION_ERROR", **kwargs)
