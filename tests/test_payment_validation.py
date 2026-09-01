"""
tests/test_payment_validation.py — Phase 4 PaymentRequest validation.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.payment_request import PaymentRequest


def valid_payload(**overrides) -> dict:
    base = dict(
        request_id="req_abc123",
        user_id=1,
        agent_id=1,
        merchant_id=1,
        merchant_name="TechMart Electronics",
        amount=54999,
        currency="INR",
        category="electronics",
        description="Laptop purchase",
        agent_reason="User requested 16GB RAM laptop",
        timestamp="2026-08-26T12:00:00Z",
    )
    base.update(overrides)
    return base


def test_valid_request():
    pr = PaymentRequest(**valid_payload())
    assert pr.amount == 54999
    assert pr.currency == "INR"
    assert pr.category == "electronics"


def test_negative_amount_rejected():
    with pytest.raises(ValidationError, match="amount"):
        PaymentRequest(**valid_payload(amount=-100))

def test_zero_amount_rejected():
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(amount=0))

def test_amount_too_large_rejected():
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(amount=20_000_000))


def test_invalid_currencies():
    for cur in ["USD", "EUR", "INR ", "inr", "", "BTC"]:
        with pytest.raises(ValidationError):
            PaymentRequest(**valid_payload(currency=cur))


def test_missing_user():
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(user_id=None))
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(user_id=0))


def test_missing_agent():
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(agent_id=None))
    with pytest.raises(ValidationError):
        PaymentRequest(**{k: v for k, v in valid_payload().items() if k != "agent_id"})


def test_invalid_category():
    for cat in ["gambling_fake", "invalid", "", "   ", "crypto"]:
        with pytest.raises(ValidationError):
            PaymentRequest(**valid_payload(category=cat))
    # Blocked categories are still valid at validation layer — policy engine decides
    pr = PaymentRequest(**valid_payload(category="gambling"))
    assert pr.category == "gambling"


def test_malformed_data():
    # Bad request_id
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(request_id="ab"))  # too short
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(request_id="req with spaces"))
    # Missing merchant_name
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(merchant_name=""))
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(merchant_name="   "))
    # Bad timestamp
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(timestamp="not-a-date"))
    # Bad amount type — non-numeric string must be rejected (numeric string is coerced by pydantic)
    with pytest.raises(ValidationError):
        PaymentRequest(**valid_payload(amount="not-a-number"))  # type: ignore
    # Numeric string is coerced — ensure it still results in correct int (document behavior)
    pr_numeric = PaymentRequest(**valid_payload(amount="54999"))  # type: ignore
    assert pr_numeric.amount == 54999


def test_category_normalized():
    pr = PaymentRequest(**valid_payload(category="Electronics"))
    assert pr.category == "electronics"
    pr2 = PaymentRequest(**valid_payload(category="BOOKS"))
    assert pr2.category == "books"


def test_optional_fields():
    pr = PaymentRequest(**valid_payload(description=None, agent_reason=None, timestamp=None))
    assert pr.description is None
    # timestamp None is allowed
    assert pr.timestamp is None


def test_timestamp_normalization():
    pr = PaymentRequest(**valid_payload(timestamp="2026-08-26T12:00:00+05:30"))
    assert pr.timestamp.endswith("Z")
    pr2 = PaymentRequest(**valid_payload(timestamp="2026-08-26T12:00:00Z"))
    assert pr2.timestamp == "2026-08-26T12:00:00Z"


def test_to_db_dict():
    pr = PaymentRequest(**valid_payload())
    d = pr.to_db_dict()
    assert d["request_id"] == "req_abc123"
    assert "timestamp" not in d  # DB stores created_at separately
