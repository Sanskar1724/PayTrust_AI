"""
engines/policy_engine.py — Deterministic authorization (Phase 3).

Answers:
  - Is amount allowed?
  - Is category allowed?
  - Is daily limit exceeded?
  - Is approval required?
  - Is the agent authorized?
  - Is merchant restricted?

Return:
  {
    "authorized": bool,
    "requires_approval": bool,
    "violations": [str],
    "reasons": [str]
  }

Deterministic — LLM must never override. Rules are documented below, not magic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database import repositories as repo
from core.exceptions import PolicyError


@dataclass(frozen=True)
class Policy:
    """Materialized agent policy row."""
    user_id: int
    agent_id: int
    daily_limit: int
    max_transaction: int
    approval_threshold: int
    allowed_categories: list[str]
    blocked_categories: list[str]
    allowed_merchants: list[str] | None = None
    blocked_merchants: list[str] | None = None
    is_active: bool = True


DEFAULT_POLICY = Policy(
    user_id=1,
    agent_id=1,
    daily_limit=100_000,
    max_transaction=60_000,
    approval_threshold=30_000,
    allowed_categories=["electronics", "books", "travel"],
    blocked_categories=["gambling", "financial_products"],
    allowed_merchants=None,
    blocked_merchants=None,
)


class PolicyEngine:
    """
    Deterministic policy evaluator.

    Usage (pure, no DB):
      engine = PolicyEngine()
      result = engine.evaluate(policy_dict, payment_request_dict, daily_spent=0)

    Usage (with DB — checks existence + daily spend):
      result = engine.evaluate_request(user_id, agent_id, amount, category, merchant_id, merchant_name)
    """

    def evaluate(
        self,
        policy: dict | Policy | None,
        payment: dict[str, Any],
        daily_spent: int = 0,
    ) -> dict[str, Any]:
        """
        Pure evaluation — no DB I/O. Useful for unit tests.

        policy: dict with daily_limit, max_transaction, approval_threshold, allowed/blocked categories/merchants OR Policy dataclass.
        payment: {amount, category, merchant_id, merchant_name} — at minimum.
        daily_spent: sum of already-approved amounts today (INR).

        Returns structured result.
        """
        violations: list[str] = []
        reasons: list[str] = []

        # Normalize policy
        if policy is None:
            violations.append("missing_policy")
            reasons.append("No active policy found for user+agent — agent is not authorized.")
            return {
                "authorized": False,
                "requires_approval": False,
                "violations": violations,
                "reasons": reasons,
            }

        if isinstance(policy, Policy):
            pol = policy
        else:
            # Dict from repo.get_policy or hand-crafted test dict — be lenient
            try:
                pol = Policy(
                    user_id=int(policy.get("user_id", 0)),
                    agent_id=int(policy.get("agent_id", 0)),
                    daily_limit=int(policy["daily_limit"]),
                    max_transaction=int(policy["max_transaction"]),
                    approval_threshold=int(policy["approval_threshold"]),
                    allowed_categories=[str(c).lower() for c in (policy.get("allowed_categories") or [])],
                    blocked_categories=[str(c).lower() for c in (policy.get("blocked_categories") or [])],
                    allowed_merchants=policy.get("allowed_merchants"),
                    blocked_merchants=policy.get("blocked_merchants"),
                    is_active=bool(policy.get("is_active", True)),
                )
            except Exception as exc:
                raise PolicyError(f"Malformed policy: {exc}") from exc

        amount = payment.get("amount")
        category = str(payment.get("category", "")).lower().strip()
        merchant_id = payment.get("merchant_id")
        merchant_name = payment.get("merchant_name") or (str(merchant_id) if merchant_id is not None else "")

        # — Invalid payment data (structural) —
        if not isinstance(amount, int) or amount < 1:
            violations.append("invalid_amount")
            reasons.append(f"Amount must be positive integer INR, got {amount!r}.")

        if not category:
            violations.append("missing_category")
            reasons.append("Category is required.")

        # If structural invalid, short-circuit authorized=False but continue collecting
        # — Amount above maximum —
        if isinstance(amount, int) and amount > pol.max_transaction:
            violations.append("max_transaction_exceeded")
            reasons.append(f"Amount INR {amount:,} exceeds max transaction INR {pol.max_transaction:,}.")

        # — Blocked category —
        if category and category in [c.lower() for c in pol.blocked_categories]:
            violations.append("category_blocked")
            reasons.append(f"Category '{category}' is blocked by policy.")

        # — Allowed category (if allowlist non-empty) —
        if category and pol.allowed_categories:
            if category not in [c.lower() for c in pol.allowed_categories]:
                violations.append("category_not_allowed")
                reasons.append(f"Category '{category}' is not in allowed categories {pol.allowed_categories}.")

        # — Restricted merchant —
        if pol.blocked_merchants and (merchant_name in pol.blocked_merchants or str(merchant_id) in pol.blocked_merchants):
            violations.append("merchant_blocked")
            reasons.append(f"Merchant '{merchant_name}' is blocked by policy.")

        if pol.allowed_merchants is not None and len(pol.allowed_merchants) > 0:
            if merchant_name not in pol.allowed_merchants and str(merchant_id) not in pol.allowed_merchants:
                violations.append("merchant_not_allowed")
                reasons.append(f"Merchant '{merchant_name}' not in allowed merchants {pol.allowed_merchants}.")

        # — Daily limit exceeded —
        if isinstance(amount, int):
            projected = daily_spent + amount
            if projected > pol.daily_limit:
                violations.append("daily_limit_exceeded")
                reasons.append(
                    f"Daily limit INR {pol.daily_limit:,} exceeded: already spent INR {daily_spent:,} + INR {amount:,} = INR {projected:,}."
                )

        # — Inactive policy / agent not authorized —
        if not pol.is_active:
            # Agent authorized violation supersedes category/amount? Still include above, but mark explicitly
            if "missing_policy" not in violations:
                violations.append("agent_unauthorized")
                reasons.append("Agent policy is inactive — agent is not authorized for this user.")

        # — Approval required? (independent of authorized) —
        requires_approval = False
        if isinstance(amount, int) and amount > pol.approval_threshold:
            requires_approval = True
            reasons.append(f"Amount INR {amount:,} exceeds approval threshold INR {pol.approval_threshold:,} — requires user approval.")

        authorized = len([v for v in violations if v not in ("requires_approval",)]) == 0
        # authorized means no blocking violations; requires_approval can still be True
        # If any blocking violation exists, authorized=False
        blocking = {v for v in violations if v not in ()}
        # All violations are blocking except we intentionally keep requires_approval out — currently all are blocking
        authorized = len(violations) == 0

        if authorized and not requires_approval:
            reasons.append("Payment within policy — no approval required.")
        elif authorized and requires_approval:
            # keep approval reason already added
            pass

        return {
            "authorized": authorized,
            "requires_approval": requires_approval,
            "violations": violations,
            "reasons": reasons,
            "policy": {
                "daily_limit": pol.daily_limit,
                "max_transaction": pol.max_transaction,
                "approval_threshold": pol.approval_threshold,
                "allowed_categories": pol.allowed_categories,
                "blocked_categories": pol.blocked_categories,
            },
        }

    def evaluate_request(
        self,
        user_id: int,
        agent_id: int,
        amount: int,
        category: str,
        merchant_id: int | None = None,
        merchant_name: str | None = None,
        db_path: Path | None = None,
    ) -> dict[str, Any]:
        """
        DB-backed evaluation — fetches policy + merchant + daily spend.
        Missing user/agent/merchant/policy are treated as violations.
        """
        violations: list[str] = []
        reasons: list[str] = []

        # Existence checks (parameterized queries via repo)
        user = repo.get_user(user_id, db_path=db_path) if user_id is not None else None
        agent = repo.get_agent(agent_id, db_path=db_path) if agent_id is not None else None
        policy = repo.get_policy(user_id, agent_id, db_path=db_path) if user_id and agent_id else None
        merchant = repo.get_merchant(merchant_id, db_path=db_path) if merchant_id is not None else None

        if user_id is None or user is None:
            violations.append("missing_user")
            reasons.append(f"User id {user_id!r} not found.")
        if agent_id is None or agent is None:
            violations.append("unauthorized_agent")
            reasons.append(f"Agent id {agent_id!r} not found or inactive.")
        elif agent and not agent.get("is_active"):
            violations.append("unauthorized_agent")
            reasons.append(f"Agent '{agent.get('agent_name')}' is inactive.")

        if merchant_id is not None and merchant is None:
            violations.append("missing_merchant")
            reasons.append(f"Merchant id {merchant_id!r} not found.")

        # Merchant category vs policy? Use provided category, but if merchant has its own category, surface mismatch
        if merchant and category and merchant.get("category"):
            merchant_cat = str(merchant["category"]).lower()
            if merchant_cat != category.lower():
                reasons.append(f"Note: merchant category is '{merchant_cat}' but request category is '{category}'.")

        # Daily spent from DB (today UTC)
        daily_spent = 0
        if user and agent and policy:
            try:
                daily_spent = repo.get_daily_spent(user_id, db_path=db_path)
            except Exception:
                daily_spent = 0

        # If policy missing, we already have violation — still run pure evaluator with None to get its reasons
        if policy is None:
            # Missing policy is the canonical violation; avoid double counting missing_policy via evaluate
            pure = self.evaluate(None, {"amount": amount, "category": category, "merchant_id": merchant_id, "merchant_name": merchant_name or (merchant.get("name") if merchant else "")}, daily_spent=daily_spent)
            # Merge but prefer our existence violations
            for v in pure["violations"]:
                if v not in violations:
                    violations.append(v)
            for r in pure["reasons"]:
                if r not in reasons:
                    reasons.append(r)
            return {
                "authorized": False,
                "requires_approval": pure.get("requires_approval", False),
                "violations": violations,
                "reasons": reasons,
            }

        pure = self.evaluate(
            policy,
            {"amount": amount, "category": category, "merchant_id": merchant_id, "merchant_name": merchant_name or merchant.get("name") if merchant else merchant_name},
            daily_spent=daily_spent,
        )
        # Merge existence violations with policy violations
        for v in pure["violations"]:
            if v not in violations:
                violations.append(v)
        # Insert structural reasons after existence ones
        reasons.extend([r for r in pure["reasons"] if r not in reasons])

        # Agent authorization: if agent missing/inactive, ensure authorized stays False
        if "unauthorized_agent" in violations or "missing_user" in violations:
            authorized = False
        else:
            authorized = pure["authorized"] and "unauthorized_agent" not in violations

        return {
            "authorized": authorized,
            "requires_approval": pure["requires_approval"],
            "violations": violations,
            "reasons": reasons,
            "policy": pure.get("policy"),
            "daily_spent": daily_spent,
        }
