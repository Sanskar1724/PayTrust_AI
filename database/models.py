"""
database/models.py — Pydantic models for SQLite rows (validation boundary).

Phase 4 will expand PaymentRequest validation; for Phase 1 keep minimal.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class UserModel(BaseModel):
    id: Optional[int] = None
    email: str
    name: str
    role: str = "VIEWER"


class AgentModel(BaseModel):
    id: Optional[int] = None
    agent_name: str
    description: Optional[str] = None
    is_active: bool = True


class MerchantModel(BaseModel):
    id: Optional[int] = None
    name: str
    category: Optional[str] = None
    region: Optional[str] = None


class PaymentRequestModel(BaseModel):
    request_id: str
    user_id: int
    agent_id: int
    merchant_id: int
    merchant_name: str
    amount: int = Field(..., ge=1, description="Amount in INR, must be >=1")
    currency: str = Field(default="INR", pattern="^(INR)$")
    category: str
    description: Optional[str] = None
    agent_reason: Optional[str] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        allowed = {"electronics", "books", "travel", "food", "fashion", "grocery", "fuel", "gambling", "financial_products"}
        if v.lower() not in allowed:
            raise ValueError(f"Invalid category '{v}'. Allowed: {sorted(allowed)}")
        return v.lower()
