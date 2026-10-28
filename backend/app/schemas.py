"""API request/response schemas."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

CATEGORIES = ("electronics", "books", "travel", "food", "fashion", "grocery", "fuel", "gambling", "financial_products")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
MAX_AMOUNT = 10_000_000


def _normalize_categories(values: list[str]) -> list[str]:
    out = []
    for v in values:
        low = v.lower().strip()
        if low not in CATEGORIES:
            raise ValueError(f"Unknown category '{v}'. Allowed: {list(CATEGORIES)}")
        if low not in out:
            out.append(low)
    return out


# ── Payments ──

class PaymentIn(BaseModel):
    """What an AI agent submits before spending money."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "request_id": "order_7f3a91c2",
        "user_id": 1,
        "merchant_id": 1,
        "merchant_name": "TechMart Electronics",
        "amount": 25000,
        "currency": "INR",
        "category": "electronics",
        "description": "Laptop, 16GB RAM",
        "agent_reason": "User asked for a laptop under INR 30,000",
    }})

    request_id: str = Field(description="Client-generated idempotency key, 6-64 chars [A-Za-z0-9_-]")
    user_id: int = Field(ge=1)
    agent_id: int | None = Field(default=None, ge=1, description="Defaults to the agent that owns the API key")
    merchant_id: int = Field(ge=1)
    merchant_name: str = Field(min_length=1, max_length=160)
    amount: int = Field(ge=1, le=MAX_AMOUNT, description="Whole INR")
    currency: Literal["INR"] = "INR"
    category: str
    description: str | None = Field(default=None, max_length=500)
    agent_reason: str | None = Field(default=None, max_length=500)
    callback_url: str | None = Field(default=None, max_length=500, description="Where to POST the approval outcome")

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, v: str) -> str:
        if not REQUEST_ID_RE.match(v):
            raise ValueError("request_id must be 6-64 characters of [A-Za-z0-9_-]")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_is_int(cls, v: Any) -> Any:
        if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
            raise ValueError("amount must be a whole number of INR")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return _normalize_categories([v])[0]

    @field_validator("merchant_name")
    @classmethod
    def _merchant_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("merchant_name is required")
        return v.strip()

    @field_validator("callback_url")
    @classmethod
    def _callback(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("callback_url must be an http(s) URL")
        return v


class PlaygroundIn(PaymentIn):
    """Operator-submitted evaluation on behalf of a chosen agent."""

    agent_id: int = Field(ge=1)  # type: ignore[assignment]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    status: str
    decision: str
    risk_score: int
    risk_level: str
    reasons: list[str]
    requires_approval: bool = False
    user_id: int
    agent_id: int
    merchant_id: int
    merchant_name: str
    amount: int
    currency: str
    category: str
    description: str | None
    agent_reason: str | None
    source: str
    policy_result: dict[str, Any]
    risk_result: dict[str, Any]
    simulation: dict[str, Any]
    ai: dict[str, Any] | None
    order: dict[str, Any] | None
    expires_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    processing_ms: float
    created_at: datetime
    updated_at: datetime
    duplicate: bool = False

    @model_validator(mode="after")
    def _approval_flag(self) -> PaymentOut:
        self.requires_approval = bool(self.policy_result.get("requires_approval")) or self.decision == "ASK_USER"
        return self


class PaymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    status: str
    decision: str
    risk_score: int
    risk_level: str
    user_id: int
    agent_id: int
    merchant_name: str
    amount: int
    category: str
    source: str
    expires_at: datetime | None
    created_at: datetime


class Page(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


# ── Auth / operators ──

class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)  # matched against stored emails, not re-validated
    password: str = Field(min_length=1, max_length=200)


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    operator: OperatorOut


class OperatorIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "reviewer", "viewer"] = "viewer"
    password: str = Field(min_length=8, max_length=200)


# ── Users / agents / merchants / policies ──

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    external_ref: str | None = Field(default=None, max_length=120)


class UserOut(UserIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None = None
    created_at: datetime


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    callback_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class AgentPatch(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    callback_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown once — store it securely")


class ApiKeyIn(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=80)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    callback_url: str | None
    is_active: bool
    created_at: datetime
    keys: list[ApiKeyOut] = []


class AgentCreated(AgentOut):
    webhook_secret: str = Field(description="Used to verify PayTrust callbacks — shown once")


class MerchantIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str | None = None
    risk_tier: Literal["standard", "high"] = "standard"

    @field_validator("category")
    @classmethod
    def _category(cls, v: str | None) -> str | None:
        return _normalize_categories([v])[0] if v else None


class MerchantOut(MerchantIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class PolicyIn(BaseModel):
    user_id: int = Field(ge=1)
    agent_id: int = Field(ge=1)
    daily_limit: int = Field(ge=0, le=MAX_AMOUNT)
    max_transaction: int = Field(ge=0, le=MAX_AMOUNT)
    approval_threshold: int = Field(ge=0, le=MAX_AMOUNT)
    allowed_categories: list[str] = []
    blocked_categories: list[str] = []
    allowed_merchants: list[str] | None = None
    blocked_merchants: list[str] | None = None
    is_active: bool = True

    @field_validator("allowed_categories", "blocked_categories")
    @classmethod
    def _cats(cls, v: list[str]) -> list[str]:
        return _normalize_categories(v)

    @model_validator(mode="after")
    def _consistent(self) -> PolicyIn:
        if self.max_transaction > self.daily_limit:
            raise ValueError("max_transaction cannot exceed daily_limit")
        if self.approval_threshold > self.max_transaction:
            raise ValueError("approval_threshold cannot exceed max_transaction")
        overlap = set(self.allowed_categories) & set(self.blocked_categories)
        if overlap:
            raise ValueError(f"categories cannot be both allowed and blocked: {sorted(overlap)}")
        return self


class PolicyOut(PolicyIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime
    updated_by: str | None

    @model_validator(mode="after")
    def _consistent(self) -> PolicyOut:  # stored rows are trusted; skip input checks
        return self


# ── Misc ──

class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor: str
    event_type: str
    request_id: str | None
    data: dict[str, Any]


class ArenaRunIn(BaseModel):
    scenario: str = "mixed"
    requests: int = Field(default=60, ge=1, le=2000)
    concurrency: int = Field(default=4, ge=1, le=32)


class ArenaRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario: str
    status: str
    params: dict[str, Any]
    stats: dict[str, Any]
    error: str | None
    started_by: str
    started_at: datetime
    finished_at: datetime | None
