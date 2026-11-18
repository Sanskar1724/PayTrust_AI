"""Deterministic policy evaluation — pure, no I/O. The LLM can never override this.

Rules (all from the user+agent policy row):
  * amount > max_transaction                       → max_transaction_exceeded
  * category in blocked_categories                 → category_blocked
  * category not in allowed_categories (if set)    → category_not_allowed
  * merchant's registered category is blocked      → merchant_category_blocked
  * merchant blocked / not in merchant allowlist   → merchant_blocked / merchant_not_allowed
  * this agent's spend today + amount > daily_limit → daily_limit_exceeded
  * … this week / this month > weekly_limit / monthly_limit (optional)
                                                   → weekly_limit_exceeded / monthly_limit_exceeded
  * this agent's spend today in the payment's category / at its merchant + amount
    > category_limits[category] / merchant_limits[merchant id or name] (optional)
                                                   → category_limit_exceeded / merchant_limit_exceeded
    (the category is the merchant's REGISTERED category when known, so relabelling a
    purchase cannot dodge a category limit)
  * requested outside allowed_from–allowed_until (local time, may wrap past midnight)
                                                   → outside_allowed_hours
  * requested on a day not in allowed_days        → outside_allowed_days
  * policy inactive                                → agent_unauthorized

User budget (optional, on the user; caps ALL of the user's agents together):
  * user's spend today / this week / this month + amount > budget
                                                   → user_daily_budget_exceeded /
                                                     user_weekly_budget_exceeded /
                                                     user_monthly_budget_exceeded

Spend counts ALLOWED + APPROVED + PENDING_APPROVAL (a pending payment reserves its amount)
and always EXCLUDES the payment being evaluated. Weeks run Monday–Sunday and months are
calendar months, both in SPEND_TIMEZONE.
  * amount > approval_threshold                    → requires_approval (not a violation)

Preconditions found by the caller (unknown user, inactive agent, …) are passed in and
always make the result unauthorized.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # index = datetime.weekday()


@dataclass(frozen=True)
class Spend:
    """Budget already used (or reserved) in each period, EXCLUDING the payment being evaluated."""
    day: int = 0
    week: int = 0
    month: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


BUDGET_PERIODS = (("daily", "day", "today"), ("weekly", "week", "this week"), ("monthly", "month", "this month"))


@dataclass(frozen=True)
class PolicyRules:
    daily_limit: int
    max_transaction: int
    approval_threshold: int
    allowed_categories: tuple[str, ...] = ()
    blocked_categories: tuple[str, ...] = ()
    allowed_merchants: tuple[str, ...] | None = None
    blocked_merchants: tuple[str, ...] | None = None
    is_active: bool = True
    weekly_limit: int | None = None
    monthly_limit: int | None = None
    category_limits: dict[str, int] | None = None   # category → daily cap for this agent
    merchant_limits: dict[str, int] | None = None   # merchant id or name (casefolded) → daily cap
    allowed_from: str | None = None                 # "HH:MM", local; with allowed_until
    allowed_until: str | None = None                # "HH:MM", exclusive; before allowed_from = overnight
    allowed_days: tuple[str, ...] | None = None     # subset of WEEKDAYS

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PolicyRules:
        def _lower(items) -> tuple[str, ...]:
            return tuple(str(c).lower().strip() for c in (items or []))

        return cls(
            daily_limit=int(d["daily_limit"]),
            max_transaction=int(d["max_transaction"]),
            approval_threshold=int(d["approval_threshold"]),
            allowed_categories=_lower(d.get("allowed_categories")),
            blocked_categories=_lower(d.get("blocked_categories")),
            allowed_merchants=tuple(str(m) for m in d["allowed_merchants"]) if d.get("allowed_merchants") else None,
            blocked_merchants=tuple(str(m) for m in d["blocked_merchants"]) if d.get("blocked_merchants") else None,
            is_active=bool(d.get("is_active", True)),
            weekly_limit=int(d["weekly_limit"]) if d.get("weekly_limit") is not None else None,
            monthly_limit=int(d["monthly_limit"]) if d.get("monthly_limit") is not None else None,
            category_limits={str(k).lower().strip(): int(v) for k, v in d["category_limits"].items()}
            if d.get("category_limits") else None,
            merchant_limits={str(k).strip().casefold(): int(v) for k, v in d["merchant_limits"].items()}
            if d.get("merchant_limits") else None,
            allowed_from=d.get("allowed_from") or None,
            allowed_until=d.get("allowed_until") or None,
            allowed_days=tuple(str(x).lower()[:3] for x in d["allowed_days"]) if d.get("allowed_days") else None,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "daily_limit": self.daily_limit,
            "max_transaction": self.max_transaction,
            "approval_threshold": self.approval_threshold,
            "allowed_categories": list(self.allowed_categories),
            "blocked_categories": list(self.blocked_categories),
            "weekly_limit": self.weekly_limit,
            "monthly_limit": self.monthly_limit,
            "category_limits": dict(self.category_limits) if self.category_limits else None,
            "merchant_limits": dict(self.merchant_limits) if self.merchant_limits else None,
            "allowed_from": self.allowed_from,
            "allowed_until": self.allowed_until,
            "allowed_days": list(self.allowed_days) if self.allowed_days else None,
        }


DEFAULT_RULES = PolicyRules(
    daily_limit=100_000,
    max_transaction=60_000,
    approval_threshold=30_000,
    allowed_categories=("electronics", "books", "travel"),
    blocked_categories=("gambling", "financial_products"),
)


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def within_hours(start: str, end: str, at: time) -> bool:
    """[start, end) in local time; a window whose end is before its start runs past midnight."""
    s, e = _hhmm(start), _hhmm(end)
    return s <= at < e if s < e else at >= s or at < e


def check_time_window(rules: PolicyRules, local_time: datetime) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if rules.allowed_days:
        today = WEEKDAYS[local_time.weekday()]
        if today not in rules.allowed_days:
            days = ", ".join(d.title() for d in WEEKDAYS if d in rules.allowed_days)
            found.append(("outside_allowed_days",
                          f"This agent may pay only on {days}; the request came on a {local_time:%A}."))
    if rules.allowed_from and rules.allowed_until:
        if not within_hours(rules.allowed_from, rules.allowed_until, local_time.time()):
            found.append(("outside_allowed_hours",
                          f"This agent may pay only between {rules.allowed_from} and {rules.allowed_until}; "
                          f"the request came at {local_time:%H:%M}."))
    return found


def evaluate_policy(
    rules: PolicyRules | dict[str, Any] | None,
    payment: dict[str, Any],
    daily_spent: int = 0,
    preconditions: list[tuple[str, str]] | None = None,
    *,
    agent_spend: Spend | None = None,
    user_spend: Spend | None = None,
    user_budget: dict[str, int | None] | None = None,
    scoped_spend: dict[str, int] | None = None,
    local_time: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one payment against a policy (and the user's overall budget, if any).

    payment: {amount, category, merchant_id, merchant_name, merchant_category?}
    agent_spend: what THIS agent already spent for this user, per period (excluding this payment).
        `daily_spent` is a shorthand for Spend(day=daily_spent) when agent_spend is not given.
    user_spend: what ALL of the user's agents already spent, per period. Needed with user_budget.
    user_budget: {"daily": int|None, "weekly": int|None, "monthly": int|None}; None = no cap.
    scoped_spend: {"category": int, "merchant": int}: this agent's spend today in the payment's
        (registered) category and at its merchant, excluding this payment. Needed for
        category_limits / merchant_limits.
    local_time: when the agent asked, in SPEND_TIMEZONE. Needed for time windows; without it
        allowed_from / allowed_until / allowed_days are not checked.
    preconditions: [(violation_code, reason)] discovered by the caller.

    Returns {authorized, requires_approval, violations, reasons, policy, daily_spent, spend, user_budget}.
    """
    agent_spend = agent_spend or Spend(day=daily_spent)
    daily_spent = agent_spend.day
    budget = {k: v for k, v in (user_budget or {}).items() if v is not None}
    spend_report = {"agent": agent_spend.as_dict(), "user": (user_spend or agent_spend).as_dict()}
    violations: list[str] = []
    reasons: list[str] = []
    for code, reason in preconditions or []:
        violations.append(code)
        reasons.append(reason)

    if rules is None:
        if "missing_policy" not in violations:
            violations.append("missing_policy")
            reasons.append("No policy exists for this user and agent — the agent is not authorized.")
        return {
            "authorized": False,
            "requires_approval": False,
            "violations": violations,
            "reasons": reasons,
            "policy": None,
            "daily_spent": daily_spent,
            "spend": spend_report,
            "user_budget": budget or None,
        }
    if isinstance(rules, dict):
        rules = PolicyRules.from_dict(rules)

    amount = payment.get("amount")
    category = str(payment.get("category") or "").lower().strip()
    merchant_id = payment.get("merchant_id")
    merchant_name = str(payment.get("merchant_name") or merchant_id or "")
    merchant_category = str(payment.get("merchant_category") or "").lower().strip()
    # Callers must pass the merchant's REGISTERED name, never the agent's claim.
    merchant_keys = {merchant_name.casefold(), str(merchant_id)}
    allowed_merchants = {m.strip().casefold() for m in rules.allowed_merchants or ()}
    blocked_merchants = {m.strip().casefold() for m in rules.blocked_merchants or ()}

    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        violations.append("invalid_amount")
        reasons.append(f"Amount must be a positive whole number of INR, got {amount!r}.")
        amount = None
    if not category:
        violations.append("missing_category")
        reasons.append("Category is required.")

    if amount is not None and amount > rules.max_transaction:
        violations.append("max_transaction_exceeded")
        reasons.append(f"Amount INR {amount:,} exceeds the per-transaction maximum of INR {rules.max_transaction:,}.")

    if category and category in rules.blocked_categories:
        violations.append("category_blocked")
        reasons.append(f"Category '{category}' is blocked by policy.")
    elif category and rules.allowed_categories and category not in rules.allowed_categories:
        violations.append("category_not_allowed")
        reasons.append(f"Category '{category}' is not in the allowed categories {list(rules.allowed_categories)}.")

    # The agent chooses `category`; the merchant's registered category is ground truth.
    if merchant_category and merchant_category != category and merchant_category in rules.blocked_categories:
        violations.append("merchant_category_blocked")
        reasons.append(
            f"Merchant '{merchant_name}' is registered as '{merchant_category}', which is blocked — "
            f"the request claimed '{category}'."
        )

    if blocked_merchants and merchant_keys & blocked_merchants:
        violations.append("merchant_blocked")
        reasons.append(f"Merchant '{merchant_name}' is blocked by policy.")
    if allowed_merchants and not merchant_keys & allowed_merchants:
        violations.append("merchant_not_allowed")
        reasons.append(f"Merchant '{merchant_name}' is not in the merchant allowlist.")

    if amount is not None:
        projected = daily_spent + amount
        if projected > rules.daily_limit:
            violations.append("daily_limit_exceeded")
            reasons.append(
                f"Daily limit INR {rules.daily_limit:,} exceeded: INR {daily_spent:,} already used today "
                f"by this agent + INR {amount:,} = INR {projected:,}."
            )
        for limit, used, code, name, label in (
            (rules.weekly_limit, agent_spend.week, "weekly_limit_exceeded", "Weekly", "this week"),
            (rules.monthly_limit, agent_spend.month, "monthly_limit_exceeded", "Monthly", "this month"),
        ):
            if limit is not None and used + amount > limit:
                violations.append(code)
                reasons.append(
                    f"{name} limit INR {limit:,} exceeded: INR {used:,} already used {label} "
                    f"by this agent + INR {amount:,} = INR {used + amount:,}."
                )
        scoped = scoped_spend or {}
        limit_category = merchant_category or category
        cat_cap = (rules.category_limits or {}).get(limit_category)
        if cat_cap is not None and scoped.get("category", 0) + amount > cat_cap:
            used = scoped.get("category", 0)
            violations.append("category_limit_exceeded")
            reasons.append(
                f"Daily limit for '{limit_category}' INR {cat_cap:,} exceeded: INR {used:,} already used today "
                f"in this category by this agent + INR {amount:,} = INR {used + amount:,}."
            )
        merchant_caps = [v for k, v in (rules.merchant_limits or {}).items() if k in merchant_keys]
        if merchant_caps and scoped.get("merchant", 0) + amount > min(merchant_caps):
            cap, used = min(merchant_caps), scoped.get("merchant", 0)
            violations.append("merchant_limit_exceeded")
            reasons.append(
                f"Daily limit at '{merchant_name}' INR {cap:,} exceeded: INR {used:,} already used today at this "
                f"merchant by this agent + INR {amount:,} = INR {used + amount:,}."
            )
        totals = user_spend or agent_spend
        for key, period, label in BUDGET_PERIODS:
            cap = budget.get(key)
            used = getattr(totals, period)
            if cap is not None and used + amount > cap:
                violations.append(f"user_{key}_budget_exceeded")
                reasons.append(
                    f"The user's {key} budget of INR {cap:,} for all agents together is exceeded: INR {used:,} "
                    f"already used {label} + INR {amount:,} = INR {used + amount:,}."
                )

    if local_time is not None:
        for code, reason in check_time_window(rules, local_time):
            violations.append(code)
            reasons.append(reason)

    if not rules.is_active:
        violations.append("agent_unauthorized")
        reasons.append("The policy for this agent is inactive — the agent is not authorized.")

    requires_approval = amount is not None and amount > rules.approval_threshold
    if requires_approval:
        reasons.append(
            f"Amount INR {amount:,} is above the approval threshold of INR {rules.approval_threshold:,} — "
            "the user must approve."
        )

    authorized = not violations
    if authorized and not requires_approval:
        reasons.append("Payment is within policy.")

    return {
        "authorized": authorized,
        "requires_approval": requires_approval,
        "violations": violations,
        "reasons": reasons,
        "policy": rules.summary(),
        "daily_spent": daily_spent,
        "spend": spend_report | ({"scoped_today": scoped_spend} if scoped_spend is not None else {}),
        "user_budget": budget or None,
    }
