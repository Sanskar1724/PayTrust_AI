"""ORM models.

Payments are a single row holding the request, the decision and its evidence, so the
whole evaluation is written atomically. Payments deliberately carry no foreign keys to
users/agents/merchants: a request naming an unknown user must still be recorded (and DENIED).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, insert
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


class PaymentStatus:
    ALLOWED = "ALLOWED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"

    ALL = (ALLOWED, PENDING_APPROVAL, APPROVED, REJECTED, EXPIRED, DENIED)
    # Statuses that consume (or reserve) the payer's daily budget.
    COUNTS_TOWARD_SPEND = (ALLOWED, PENDING_APPROVAL, APPROVED)
    # Statuses that represent completed, trusted history.
    SUCCESSFUL = (ALLOWED, APPROVED)


class Role:
    ADMIN = "admin"
    REVIEWER = "reviewer"
    VIEWER = "viewer"

    ALL = (ADMIN, REVIEWER, VIEWER)
    RANK = {VIEWER: 0, REVIEWER: 1, ADMIN: 2}


class Operator(Base):
    """A dashboard login (admin / reviewer / viewer)."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default=Role.VIEWER)
    password_hash: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class User(Base):
    """A payer — the person an AI agent spends on behalf of."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    # Optional overall budget across ALL of this user's agents (None = no cap).
    daily_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    def budget(self) -> dict[str, int | None]:
        return {"daily": self.daily_budget, "weekly": self.weekly_budget, "monthly": self.monthly_budget}


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    keys: Mapped[list[ApiKey]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class ApiKey(Base):
    """Agent credential. Only a SHA-256 of the secret is stored; the full key is shown once."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="default")
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="keys")


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_tier: Mapped[str] = mapped_column(String(16), default="standard")  # standard | high
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Policy(Base):
    """What one agent may spend on behalf of one user."""

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("user_id", "agent_id", name="uq_policy_user_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    daily_limit: Mapped[int] = mapped_column(Integer)
    weekly_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)   # None = no weekly limit
    monthly_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = no monthly limit
    max_transaction: Mapped[int] = mapped_column(Integer)
    approval_threshold: Mapped[int] = mapped_column(Integer)
    allowed_categories: Mapped[list[str]] = mapped_column(JSONType, default=list)
    blocked_categories: Mapped[list[str]] = mapped_column(JSONType, default=list)
    allowed_merchants: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    blocked_merchants: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    category_limits: Mapped[dict[str, int] | None] = mapped_column(JSONType, nullable=True)  # category → daily cap
    merchant_limits: Mapped[dict[str, int] | None] = mapped_column(JSONType, nullable=True)  # merchant id/name → cap
    allowed_from: Mapped[str | None] = mapped_column(String(5), nullable=True)    # "HH:MM" local, with allowed_until
    allowed_until: Mapped[str | None] = mapped_column(String(5), nullable=True)   # "HH:MM", exclusive
    allowed_days: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)  # ["mon", …]; None = every day
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on every change to the rules; each version's rules are kept in policy_versions.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(254), nullable=True)

    def as_rules(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "daily_limit": self.daily_limit,
            "weekly_limit": self.weekly_limit,
            "monthly_limit": self.monthly_limit,
            "max_transaction": self.max_transaction,
            "approval_threshold": self.approval_threshold,
            "allowed_categories": list(self.allowed_categories or []),
            "blocked_categories": list(self.blocked_categories or []),
            "allowed_merchants": list(self.allowed_merchants) if self.allowed_merchants else None,
            "blocked_merchants": list(self.blocked_merchants) if self.blocked_merchants else None,
            "category_limits": dict(self.category_limits) if self.category_limits else None,
            "merchant_limits": dict(self.merchant_limits) if self.merchant_limits else None,
            "allowed_from": self.allowed_from,
            "allowed_until": self.allowed_until,
            "allowed_days": list(self.allowed_days) if self.allowed_days else None,
            "is_active": self.is_active,
        }


class PolicyVersion(Base):
    """An immutable copy of a policy's rules. Written automatically whenever a policy is created
    or its rules change (see the mapper events below), whoever makes the change."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version", name="uq_policy_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[dict] = mapped_column(JSONType)
    updated_by: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# Every column of a policy except bookkeeping is a rule: changing one creates a new version.
_POLICY_BOOKKEEPING = {"id", "version", "updated_at", "updated_by"}


def _snapshot(connection, policy: Policy) -> None:
    connection.execute(insert(PolicyVersion.__table__).values(
        policy_id=policy.id, user_id=policy.user_id, agent_id=policy.agent_id, version=policy.version,
        rules=policy.as_rules(), updated_by=policy.updated_by, created_at=utcnow(),
    ))


@event.listens_for(Policy, "before_insert")
def _policy_first_version(mapper, connection, policy: Policy) -> None:
    policy.version = 1


@event.listens_for(Policy, "after_insert")
def _policy_snapshot_insert(mapper, connection, policy: Policy) -> None:
    _snapshot(connection, policy)


@event.listens_for(Policy, "before_update")
def _policy_bump_version(mapper, connection, policy: Policy) -> None:
    state = sa_inspect(policy)
    changed = False
    for attr in mapper.column_attrs:
        if attr.key in _POLICY_BOOKKEEPING:
            continue
        history = state.attrs[attr.key].history
        # Re-saving a rule with the same value is not a change (SQLAlchemy still records the set).
        if history.added and list(history.added) != list(history.deleted):
            changed = True
            break
    if changed:
        policy.version = (policy.version or 1) + 1
    policy.__dict__["_rules_changed"] = changed  # plain attribute, not a column


@event.listens_for(Policy, "after_update")
def _policy_snapshot_update(mapper, connection, policy: Policy) -> None:
    if policy.__dict__.pop("_rules_changed", False):
        _snapshot(connection, policy)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_user_day_status", "user_id", "spend_day", "status"),
        Index("ix_payments_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="api")  # api | playground | arena

    user_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True)
    # The API key that submitted the request (None for playground). Revoking it blocks approval.
    api_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # The policy version that decided this payment (None when there was no policy).
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_name: Mapped[str] = mapped_column(String(160))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(10))
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(10))
    reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    policy_result: Mapped[dict] = mapped_column(JSONType, default=dict)
    risk_result: Mapped[dict] = mapped_column(JSONType, default=dict)
    simulation: Mapped[dict] = mapped_column(JSONType, default=dict)
    ai: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    order: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    spend_day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD in SPEND_TIMEZONE
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(254), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_ms: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(254))
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class JobStatus:
    PENDING = "PENDING"   # waiting for run_after
    RUNNING = "RUNNING"   # claimed by a worker until locked_until (then reclaimable)
    DONE = "DONE"
    DEAD = "DEAD"         # retries exhausted or permanent failure: the dead-letter queue

    ALL = (PENDING, RUNNING, DONE, DEAD)


class Job(Base):
    """Durable background work (transactional outbox): written in the same transaction as the
    change that needs it, executed by a worker with retries. See services/jobs.py."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(10), default=JobStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WebhookEvent(Base):
    """Inbound Razorpay webhook — event_id uniqueness gives idempotency."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    event_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="PROCESSED")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ArenaRun(Base):
    __tablename__ = "arena_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")  # RUNNING | COMPLETED | FAILED
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str] = mapped_column(String(254))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
