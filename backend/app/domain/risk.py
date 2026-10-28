"""Transparent risk scoring — pure, no I/O.

Each dimension adds documented points; the total is capped at 100 and any
critical factor lifts the score to at least 65. Every point is explained by a factor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config import get_settings
from app.errors import ValidationFailed

HIGH_RISK_CATEGORIES = ("gambling", "financial_products")

# (threshold, points, severity) — first match wins
AMOUNT_BANDS = [(50_000, 20, "high"), (30_000, 12, "medium"), (15_000, 5, "low")]
SPEND_RATIO_BANDS = [(0.9, 20, "high"), (0.7, 12, "medium"), (0.5, 6, "low")]
FREQUENCY_BANDS = [(10, 20, "high"), (5, 12, "medium"), (3, 6, "low")]
DUPLICATE_WINDOW_MINUTES = 10
DUPLICATE_HIGH = 3  # this many identical recent attempts → high risk on its own

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class RiskFactor:
    name: str
    severity: str
    score: int
    details: str


def level_for(score: int) -> str:
    s = get_settings()
    if score <= s.RISK_THRESHOLD_LOW:
        return "LOW"
    if score <= s.RISK_THRESHOLD_MEDIUM:
        return "MEDIUM"
    if score <= s.RISK_THRESHOLD_HIGH:
        return "HIGH"
    return "CRITICAL"


def assess_risk(
    payment: dict[str, Any],
    policy_result: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one payment.

    payment: {amount, category, merchant_category?, merchant_risk_tier?}
    context (all computed EXCLUDING this payment):
      daily_limit, daily_spent, transactions_last_hour, duplicates_recent,
      user_total_txns, is_new_merchant, is_new_user
    """
    if not isinstance(payment, dict):
        raise ValidationFailed("payment dict required")
    amount = payment.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        raise ValidationFailed(f"Invalid amount {amount!r}")

    context = context or {}
    violations: list[str] = (policy_result or {}).get("violations") or []
    category = str(payment.get("category") or "").lower()
    merchant_category = str(payment.get("merchant_category") or "").lower()
    merchant_tier = str(payment.get("merchant_risk_tier") or "standard").lower()

    factors: list[RiskFactor] = []

    # 1. Amount
    for threshold, pts, sev in AMOUNT_BANDS:
        if amount >= threshold:
            factors.append(RiskFactor("amount_risk", sev, pts, f"Amount INR {amount:,} ≥ INR {threshold:,}"))
            break

    # 2. Spending behaviour — how much of today's budget this payment would use
    daily_limit = context.get("daily_limit")
    daily_spent = int(context.get("daily_spent") or 0)
    if isinstance(daily_limit, int) and daily_limit > 0:
        ratio = (daily_spent + amount) / daily_limit
        for threshold, pts, sev in SPEND_RATIO_BANDS:
            if ratio >= threshold:
                factors.append(RiskFactor(
                    "spending_behavior", sev, pts,
                    f"Projected spend today INR {daily_spent + amount:,} is {ratio:.0%} of the INR {daily_limit:,} limit",
                ))
                break

    # 3. Merchant
    if category in HIGH_RISK_CATEGORIES:
        factors.append(RiskFactor("merchant_risk", "critical", 25, f"High-risk category '{category}'"))
    elif merchant_category in HIGH_RISK_CATEGORIES:
        factors.append(RiskFactor("merchant_risk", "high", 20, f"Merchant is registered as high-risk '{merchant_category}'"))
    elif merchant_tier == "high":
        factors.append(RiskFactor("merchant_risk", "medium", 12, "Merchant risk tier is high"))
    if merchant_category and category and merchant_category != category:
        factors.append(RiskFactor(
            "category_mismatch", "medium", 12,
            f"Request says '{category}' but the merchant is registered as '{merchant_category}'",
        ))
    if context.get("is_new_merchant") and not any(f.severity == "critical" for f in factors):
        factors.append(RiskFactor("merchant_risk", "medium", 10, "First payment from this user to this merchant"))

    # 4. Policy — violations carry inherent risk
    policy_points = {
        "max_transaction_exceeded": ("high", 20, "Amount exceeds the policy maximum"),
        "daily_limit_exceeded": ("high", 18, "Daily limit would be exceeded"),
        "category_blocked": ("critical", 25, "Category is blocked by policy"),
        "merchant_category_blocked": ("critical", 25, "Merchant's real category is blocked by policy"),
        "category_not_allowed": ("high", 15, "Category is not in the allowlist"),
        "merchant_blocked": ("high", 15, "Merchant is restricted by policy"),
        "merchant_not_allowed": ("high", 15, "Merchant is restricted by policy"),
        "missing_merchant": ("high", 15, "Merchant is unknown"),
    }
    for code, (sev, pts, details) in policy_points.items():
        if code in violations:
            factors.append(RiskFactor("policy_risk", sev, pts, details))

    # 5. Agent authorization
    if {"unauthorized_agent", "missing_policy", "missing_user", "agent_key_mismatch"} & set(violations):
        factors.append(RiskFactor("agent_auth_risk", "critical", 25, "Agent is not authorized for this user"))
    elif "agent_unauthorized" in violations:
        factors.append(RiskFactor("agent_auth_risk", "high", 20, "Agent policy is inactive"))

    # 6. Frequency
    tx_last_hour = int(context.get("transactions_last_hour") or 0)
    for threshold, pts, sev in FREQUENCY_BANDS:
        if tx_last_hour >= threshold:
            factors.append(RiskFactor("frequency_risk", sev, pts, f"{tx_last_hour} payment attempts in the last hour"))
            break

    # 6b. Repeats — same merchant + same amount moments ago (agent stuck in a loop, replayed intent)
    duplicates = int(context.get("duplicates_recent") or 0)
    if duplicates >= DUPLICATE_HIGH:
        factors.append(RiskFactor("duplicate_payment", "high", 65,
                                  f"{duplicates} identical payments to this merchant in the last {DUPLICATE_WINDOW_MINUTES} minutes"))
    elif duplicates >= 1:
        factors.append(RiskFactor("duplicate_payment", "medium", 35,
                                  f"An identical payment to this merchant was attempted in the last {DUPLICATE_WINDOW_MINUTES} minutes"))

    # 7. History — little track record + a large amount
    user_total = int(context.get("user_total_txns") or 0)
    if user_total < 5 and amount >= 30_000:
        factors.append(RiskFactor("historical_behavior", "medium", 12, f"Only {user_total} past payments, high amount INR {amount:,}"))
    if context.get("is_new_user") and amount >= 20_000:
        factors.append(RiskFactor("historical_behavior", "medium", 10, "First-ever payment for this user"))

    raw = sum(f.score for f in factors)
    score = min(100, max(0, raw))
    if any(f.severity == "critical" for f in factors):
        score = max(score, 65)

    factors.sort(key=lambda f: (_SEVERITY_RANK.get(f.severity, 0), f.score), reverse=True)
    return {
        "risk_score": score,
        "risk_level": level_for(score),
        "raw_score": raw,
        "factors": [asdict(f) for f in factors],
    }
