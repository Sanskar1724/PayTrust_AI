"""The decision PayTrust returns for a payment."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PENDING = "PENDING_APPROVAL"
CAN_PAY = ("ALLOWED", "APPROVED")
WILL_NOT_PAY = ("DENIED", "REJECTED", "EXPIRED")


@dataclass(frozen=True)
class Decision:
    """PayTrust's answer for one payment.

    `decision` is what PayTrust decided when the agent asked (ALLOW / ASK_USER / DENY).
    `status` is where the payment is now: ALLOWED, PENDING_APPROVAL, APPROVED, REJECTED,
    EXPIRED or DENIED. Act on `status`, through the helpers below.
    """

    request_id: str
    decision: str
    status: str
    amount: int
    merchant_name: str
    risk_score: int
    risk_level: str
    reasons: list[str]
    violations: list[str]
    expires_at: str | None
    order: dict[str, Any] | None
    duplicate: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Decision:
        policy = data.get("policy_result") or {}
        return cls(
            request_id=data["request_id"],
            decision=data["decision"],
            status=data["status"],
            amount=data.get("amount", 0),
            merchant_name=data.get("merchant_name", ""),
            risk_score=data.get("risk_score", 0),
            risk_level=data.get("risk_level", ""),
            reasons=list(data.get("reasons") or []),
            violations=list(policy.get("violations") or []),
            expires_at=data.get("expires_at"),
            order=data.get("order"),
            duplicate=bool(data.get("duplicate")),
            raw=data,
        )

    @property
    def can_pay(self) -> bool:
        """True only when the money may move: ALLOWED, or APPROVED by a human."""
        return self.status in CAN_PAY

    @property
    def waiting_for_approval(self) -> bool:
        """A human must decide first. Do not pay yet; tell the user and wait."""
        return self.status == PENDING

    @property
    def refused(self) -> bool:
        """DENIED by policy/risk, or REJECTED / EXPIRED in review. Do not pay."""
        return self.status in WILL_NOT_PAY

    @property
    def is_final(self) -> bool:
        return self.status != PENDING

    def explain(self) -> str:
        """One line a user can read."""
        head = {
            "ALLOWED": "Approved instantly",
            "APPROVED": "Approved by a reviewer",
            PENDING: "Waiting for approval",
            "DENIED": "Not allowed",
            "REJECTED": "Rejected by a reviewer",
            "EXPIRED": "The approval request expired",
        }.get(self.status, self.status)
        reason = self.reasons[0] if self.reasons else ""
        return f"{head}: {reason}" if reason and not self.can_pay else head
