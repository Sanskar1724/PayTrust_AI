"""
models/payment_request.py — Phase 4 standardized Payment Request validation.

Example:
  {
    "request_id": "req_abc123",
    "user_id": 1,
    "agent_id": 1,
    "merchant_id": 1,
    "merchant_name": "TechMart Electronics",
    "amount": 54999,
    "currency": "INR",
    "category": "electronics",
    "description": "Laptop purchase",
    "agent_reason": "User requested 16GB RAM laptop",
    "timestamp": "2026-08-26T12:00:00Z"
  }

Rejects: negative amounts, invalid currencies, missing user/agent, invalid category, malformed data.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_CATEGORIES = {"electronics", "books", "travel", "food", "fashion", "grocery", "fuel", "gambling", "financial_products"}
ALLOWED_CURRENCIES = {"INR"}
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")


class PaymentRequest(BaseModel):
    request_id: str = Field(..., description="Unique request id, 6-64 alphanum/_/-")
    user_id: int = Field(..., description="Existing user id")
    agent_id: int = Field(..., description="Existing agent id")
    merchant_id: int = Field(..., description="Existing merchant id")
    merchant_name: str = Field(..., min_length=1)
    amount: int = Field(..., description="Amount in INR, must be >=1")
    currency: str = Field(default="INR")
    category: str = Field(...)
    description: Optional[str] = Field(default=None, max_length=500)
    agent_reason: Optional[str] = Field(default=None, max_length=500)
    timestamp: Optional[str] = Field(default=None, description="ISO8601 UTC timestamp")

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, v: str) -> str:
        if not REQUEST_ID_RE.match(v):
            raise ValueError("request_id must be 6-64 chars: [A-Za-z0-9_-]")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if not isinstance(v, int):
            raise ValueError("amount must be integer")
        if v < 1:
            raise ValueError("amount must be >= 1")
        if v > 10_000_000:  # 1 Cr — sanity cap
            raise ValueError("amount exceeds maximum allowed (10,000,000)")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if v not in ALLOWED_CURRENCIES:
            raise ValueError(f"Invalid currency '{v}'. Only INR supported.")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("category is required")
        low = v.lower().strip()
        if low not in ALLOWED_CATEGORIES:
            raise ValueError(f"Invalid category '{v}'. Allowed: {sorted(ALLOWED_CATEGORIES)}")
        return low

    @field_validator("merchant_name")
    @classmethod
    def validate_merchant_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("merchant_name is required")
        return v.strip()

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Accept ISO8601 — parse to validate
        try:
            # Handle Z suffix
            raw = v.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            # Normalize to UTC Z
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception as exc:
            raise ValueError(f"Invalid timestamp '{v}': {exc}") from exc

    @model_validator(mode="after")
    def check_required_ids(self) -> "PaymentRequest":
        for field in ("user_id", "agent_id", "merchant_id"):
            val = getattr(self, field)
            if val is None or (isinstance(val, int) and val < 1):
                raise ValueError(f"{field} is required and must be >=1")
        return self

    def to_db_dict(self) -> dict:
        """Return dict suitable for repositories.create_payment_request."""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "amount": self.amount,
            "currency": self.currency,
            "category": self.category,
            "description": self.description,
            "agent_reason": self.agent_reason,
        }
