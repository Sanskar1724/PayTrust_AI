"""
database/models.py — Re-export for convenience.
PaymentRequest canonical model lives in models/payment_request.py (Phase 4).
"""
from __future__ import annotations

from models.payment_request import PaymentRequest, ALLOWED_CATEGORIES, ALLOWED_CURRENCIES

from pydantic import BaseModel
from typing import Optional


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


__all__ = [
    "UserModel",
    "AgentModel",
    "MerchantModel",
    "PaymentRequest",
    "ALLOWED_CATEGORIES",
    "ALLOWED_CURRENCIES",
]
