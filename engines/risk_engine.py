"""
engines/risk_engine.py — Phase 5 deterministic Risk Engine.

Dimensions (transparent, documented):
  1. amount_risk          — absolute amount vs thresholds
  2. spending_behavior    — daily_spent + amount vs daily_limit
  3. merchant_risk        — category, risk_tier, new merchant
  4. policy_risk          — violations from PolicyEngine
  5. agent_auth_risk      — unauthorized / missing policy
  6. frequency_risk       — transactions in last hour
  7. historical_behavior  — low history + high amount

No ML yet — rules are explicit and testable.
Produces:
  {
    "risk_score": 0-100,
    "risk_level": "LOW"/"MEDIUM"/"HIGH"/"CRITICAL",
    "factors": [{"name": "...", "severity": "low|medium|high|critical", "score": int, "details": str}]
  }

Risk level thresholds (from core/config.py — not magic):
  LOW      <= 30
  MEDIUM   <= 60
  HIGH     <= 80
  CRITICAL >  80
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.exceptions import RiskEngineError
from core.logger import get_logger
from database import repositories as repo

logger = get_logger("engines.risk")
settings = get_settings()

# Documented weights — sum of max contributions ~100
# Each dimension contributes 0-25 points depending on severity
AMOUNT_THRESHOLDS = [
    (50000, 20, "high"),
    (30000, 12, "medium"),
    (15000, 5, "low"),
]
SPENDING_RATIO_THRESHOLDS = [
    (0.9, 20, "high"),
    (0.7, 12, "medium"),
    (0.5, 6, "low"),
]
FREQUENCY_THRESHOLDS = [
    (10, 20, "high"),
    (5, 12, "medium"),
    (3, 6, "low"),
]


def _level_from_score(score: int) -> str:
    if score <= settings.RISK_THRESHOLD_LOW:
        return "LOW"
    if score <= settings.RISK_THRESHOLD_MEDIUM:
        return "MEDIUM"
    if score <= settings.RISK_THRESHOLD_HIGH:
        return "HIGH"
    return "CRITICAL"


def _severity_rank(sev: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(sev, 0)


@dataclass
class RiskFactor:
    name: str
    severity: str  # low/medium/high/critical
    score: int
    details: str


class RiskEngine:
    """
    Deterministic risk scorer. Pure `assess()` for unit tests, `assess_request()` for DB-backed.
    """

    def assess(
        self,
        payment: dict[str, Any],
        policy_result: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Pure assessment — no DB I/O.

        payment: {amount, category, merchant_id, merchant_name, merchant_category, merchant_risk_tier}
        policy_result: output of PolicyEngine.evaluate (authorized, violations, requires_approval)
        context: {
            daily_limit, daily_spent, transactions_last_hour,
            user_total_txns, is_new_merchant, is_new_user
        }
        """
        if payment is None or not isinstance(payment, dict):
            raise RiskEngineError("payment dict required")
        amount = payment.get("amount")
        category = str(payment.get("category", "")).lower()
        merchant_category = str(payment.get("merchant_category", "") or category).lower()
        merchant_tier = str(payment.get("merchant_risk_tier", "standard")).lower()
        is_new_merchant = bool((context or {}).get("is_new_merchant", False))
        is_new_user = bool((context or {}).get("is_new_user", False))

        if not isinstance(amount, int) or amount < 1:
            raise RiskEngineError(f"Invalid amount {amount!r}")

        policy_result = policy_result or {}
        context = context or {}
        violations: list[str] = policy_result.get("violations", []) or []

        factors: list[RiskFactor] = []

        # 1. Amount risk
        for thresh,pts,sev in AMOUNT_THRESHOLDS:
            if amount >= thresh:
                factors.append(RiskFactor("amount_risk", sev, pts, f"Amount INR {amount:,} >= threshold INR {thresh:,}"))
                break

        # 2. Spending behavior — daily_spent + amount vs daily_limit
        daily_limit = context.get("daily_limit")
        daily_spent = context.get("daily_spent", 0)
        if isinstance(daily_limit, int) and daily_limit > 0:
            ratio = (daily_spent + amount) / daily_limit
            for r_thresh,r_pts,r_sev in SPENDING_RATIO_THRESHOLDS:
                if ratio >= r_thresh:
                    factors.append(RiskFactor("spending_behavior", r_sev, r_pts, f"Projected daily spend INR {daily_spent + amount:,} / limit INR {daily_limit:,} = {ratio:.0%}"))
                    break

        # 3. Merchant risk
        if category in ("gambling", "financial_products"):
            factors.append(RiskFactor("merchant_risk", "critical", 25, f"High-risk category '{category}'"))
        elif merchant_category in ("gambling", "financial_products"):
            factors.append(RiskFactor("merchant_risk", "high", 20, f"Merchant category '{merchant_category}' is high-risk"))
        elif merchant_tier == "high":
            factors.append(RiskFactor("merchant_risk", "medium", 12, f"Merchant risk_tier is high"))
        if is_new_merchant:
            # new merchant is medium risk unless already critical
            if not any(f.name == "merchant_risk" and f.severity == "critical" for f in factors):
                factors.append(RiskFactor("merchant_risk", "medium", 10, "First transaction with this merchant"))

        # 4. Policy risk — violations imply inherent risk
        if "max_transaction_exceeded" in violations:
            factors.append(RiskFactor("policy_risk", "high", 20, "Amount exceeds policy max_transaction"))
        if "daily_limit_exceeded" in violations:
            factors.append(RiskFactor("policy_risk", "high", 18, "Daily limit would be exceeded"))
        if "category_blocked" in violations:
            factors.append(RiskFactor("policy_risk", "critical", 25, "Category is blocked by policy"))
        if "category_not_allowed" in violations:
            factors.append(RiskFactor("policy_risk", "high", 15, "Category not in allowlist"))
        if "merchant_blocked" in violations or "merchant_not_allowed" in violations:
            factors.append(RiskFactor("policy_risk", "high", 15, "Merchant restricted by policy"))

        # 5. Agent auth risk
        if "unauthorized_agent" in violations or "missing_policy" in violations or "missing_user" in violations:
            factors.append(RiskFactor("agent_auth_risk", "critical", 25, "Agent not authorized or missing policy"))
        elif "agent_unauthorized" in violations:
            factors.append(RiskFactor("agent_auth_risk", "high", 20, "Agent inactive"))

        # 6. Frequency risk
        tx_last_hour = context.get("transactions_last_hour", 0)
        if isinstance(tx_last_hour, int) and tx_last_hour > 0:
            for f_thresh,f_pts,f_sev in FREQUENCY_THRESHOLDS:
                if tx_last_hour >= f_thresh:
                    factors.append(RiskFactor("frequency_risk", f_sev, f_pts, f"{tx_last_hour} transactions in last hour"))
                    break

        # 7. Historical behavior — new user + high amount
        user_total = context.get("user_total_txns", 0)
        if isinstance(user_total, int) and user_total < 5 and amount >= 30000:
            factors.append(RiskFactor("historical_behavior", "medium", 12, f"New user ({user_total} txns) with high amount INR {amount:,}"))
        if is_new_user and amount >= 20000:
            factors.append(RiskFactor("historical_behavior", "medium", 10, "First-ever transaction for this user"))

        # Aggregate — sum scores, cap at 100
        raw = sum(f.score for f in factors)
        risk_score = min(100, max(0, raw))
        # Boost to at least 65 if any critical factor
        if any(f.severity == "critical" for f in factors) and risk_score < 65:
            risk_score = 65
        risk_level = _level_from_score(risk_score)

        # Sort factors by severity then score descending for explainability
        factors_sorted = sorted(factors, key=lambda f: (_severity_rank(f.severity), f.score), reverse=True)

        result = {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "factors": [{"name": f.name, "severity": f.severity, "score": f.score, "details": f.details} for f in factors_sorted],
            "raw_score": raw,
        }
        logger.info(f"Risk assess amount={amount} level={risk_level} score={risk_score} factors={len(factors_sorted)}")
        return result

    def assess_request(
        self,
        user_id: int,
        agent_id: int,
        payment: dict[str, Any],
        policy_result: dict[str, Any] | None = None,
        db_path: Path | None = None,
    ) -> dict[str, Any]:
        """
        DB-backed assessment — fetches daily_spent, frequency, merchant/user history.
        """
        # Fetch policy daily_limit if not in context
        context: dict[str, Any] = {}
        try:
            pol = repo.get_policy(user_id, agent_id, db_path=db_path)
            if pol:
                context["daily_limit"] = pol["daily_limit"]
        except Exception:
            pass
        try:
            context["daily_spent"] = repo.get_daily_spent(user_id, db_path=db_path)
        except Exception:
            context["daily_spent"] = 0

        # Frequency: count payment_requests for user in last 60 minutes
        # NOTE: created_at is stored as 'YYYY-MM-DDTHH:MM:SSZ' — normalize T/Z for SQLite datetime().
        conn = None
        try:
            from database.database import get_connection
            conn = get_connection(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM payment_requests WHERE user_id = ? AND datetime(replace(replace(created_at,'T',' '),'Z','')) >= datetime('now', '-1 hour')",
                (user_id,),
            )
            context["transactions_last_hour"] = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM payment_requests WHERE user_id = ?", (user_id,))
            context["user_total_txns"] = int(cur.fetchone()[0])
            # New merchant? check if prior payment_requests with same merchant_id
            mid = payment.get("merchant_id")
            if mid is not None:
                cur.execute("SELECT COUNT(*) FROM payment_requests WHERE user_id = ? AND merchant_id = ?", (user_id, mid))
                context["is_new_merchant"] = int(cur.fetchone()[0]) == 0
            else:
                context["is_new_merchant"] = True
            context["is_new_user"] = context["user_total_txns"] == 0
        except Exception as exc:
            logger.warning(f"Risk context DB fallback: {exc}")
            # keep defaults
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        # Merchant category/tier enrichment
        try:
            mid = payment.get("merchant_id")
            if mid is not None:
                m = repo.get_merchant(int(mid), db_path=db_path)
                if m:
                    payment = dict(payment)  # copy
                    payment.setdefault("merchant_category", m.get("category"))
                    payment.setdefault("merchant_risk_tier", m.get("risk_tier"))
        except Exception:
            pass

        return self.assess(payment, policy_result=policy_result, context=context)
