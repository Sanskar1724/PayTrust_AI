"""
engines/decision_simulator.py — Phase 10 Counterfactual Decision Simulator.

Core differentiator: instead of only `Risk=82 → BLOCK`, we answer:
  What if we ALLOW? What if we ASK_USER? What if we DENY?

Estimates are SIMULATED/ESTIMATED — not real financial predictions — derived from
synthetic/evaluation data + configurable cost model. Never claim they are production forecasts.

For each action we estimate:
  fraud_exposure, false_positive_cost, operational_cost, customer_friction, expected_total_cost
Then recommend minimum expected cost, subject to hard safety constraints (policy violation → DENY).

This module is deterministic and does not call LLM or payment APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("engines.simulator")
settings = get_settings()

Decision = Literal["ALLOW", "ASK_USER", "DENY"]
Friction = Literal["low", "medium", "high"]


@dataclass
class Counterfactual:
    action: Decision
    fraud_exposure: float          # SIMULATED INR
    false_positive_cost: float     # SIMULATED INR
    operational_cost: float        # SIMULATED INR (review / block overhead)
    customer_friction: Friction
    policy_violation: bool
    expected_total_cost: float     # sum
    label: str = "SIMULATED / ESTIMATED"
    rationale: str = ""


def simulate(
    payment: dict[str, Any],
    policy_result: dict[str, Any],
    risk_result: dict[str, Any],
    decision_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Simulate ALLOW / ASK_USER / DENY for a single payment.

    Uses:
      - amount for fraud exposure base
      - risk_score → fraud probability
      - policy_result violations → hard DENY guard
      - cost model from settings (FP_*, FN_*)

    Returns:
      {
        "counterfactuals": [Counterfactual as dict],
        "recommended": "ALLOW"|"ASK_USER"|"DENY",
        "reason": str,
        "disclaimer": "SIMULATED / ESTIMATED — not real financial forecast"
      }
    """
    amount = int(payment.get("amount", 0))
    risk_score = int(risk_result.get("risk_score", 0))
    violations = policy_result.get("violations", []) or []
    has_violation = len(violations) > 0

    # Fraud probability from risk score (0-100 → 0-1), capped
    p_fraud = max(0.0, min(1.0, risk_score / 100.0))
    # If no data, use 0.05 base
    if risk_score == 0 and not has_violation:
        p_fraud = 0.02

    # Cost model — SIMULATED assumptions, from config
    fp_unit = (
        settings.FP_CUSTOMER_FRICTION_COST
        + settings.FP_SUPPORT_COST
        + settings.FP_MERCHANT_IMPACT_COST
        + amount * settings.FP_LOST_TRANSACTION_VALUE_MULTIPLIER * 0.1  # 10% of txn value as lost value proxy
    )
    fn_unit = amount * settings.FN_FRAUD_EXPOSURE_MULTIPLIER

    # Operational costs — SIMULATED
    op_allow = 0.0
    op_ask = 250.0  # manual review queue + ops
    op_deny = 120.0  # block + support

    # ALLOW: full fraud exposure if fraud, no FP cost, low friction
    allow_fraud = p_fraud * fn_unit
    allow_fp = 0.0
    allow_total = allow_fraud + allow_fp + op_allow

    # ASK_USER: review mitigates ~60% fraud, but introduces ~30% FP cost for legit users + friction
    # If fraud, review catches 60% → 40% remains; if legit, 30% chance of friction cost
    ask_fraud = p_fraud * fn_unit * 0.4
    ask_fp = (1 - p_fraud) * fp_unit * 0.3
    ask_total = ask_fraud + ask_fp + op_ask

    # DENY: blocks most fraud (95% mitigated) but high FP cost for legit
    deny_fraud = p_fraud * fn_unit * 0.05
    deny_fp = (1 - p_fraud) * fp_unit
    deny_total = deny_fraud + deny_fp + op_deny

    counterfactuals = [
        Counterfactual(
            action="ALLOW",
            fraud_exposure=round(allow_fraud, 2),
            false_positive_cost=round(allow_fp, 2),
            operational_cost=round(op_allow, 2),
            customer_friction="low",
            policy_violation=has_violation,
            expected_total_cost=round(allow_total, 2),
            rationale="Low friction, but full fraud exposure if fraud" + (" — POLICY VIOLATION would be ignored" if has_violation else ""),
        ),
        Counterfactual(
            action="ASK_USER",
            fraud_exposure=round(ask_fraud, 2),
            false_positive_cost=round(ask_fp, 2),
            operational_cost=round(op_ask, 2),
            customer_friction="medium",
            policy_violation=False,  # ASK respects policy
            expected_total_cost=round(ask_total, 2),
            rationale="Review balances fraud vs friction; policy violations are held",
        ),
        Counterfactual(
            action="DENY",
            fraud_exposure=round(deny_fraud, 2),
            false_positive_cost=round(deny_fp, 2),
            operational_cost=round(op_deny, 2),
            customer_friction="high",
            policy_violation=False,
            expected_total_cost=round(deny_total, 2),
            rationale="Safest for fraud, but high friction and FP cost if legit",
        ),
    ]

    # Hard safety: if policy violation, ALLOW is disallowed — force DENY
    if has_violation:
        recommended: Decision = "DENY"
        reason = f"Policy violation ({', '.join(violations[:2])}) — deterministic DENY overrides cost. Lowest safe cost is DENY (INR {deny_total:.0f} SIMULATED)."
    else:
        # Pick minimum expected_total_cost
        best = min(counterfactuals, key=lambda c: c.expected_total_cost)
        recommended = best.action
        reason = f"{recommended} minimizes SIMULATED expected total cost (INR {best.expected_total_cost:.0f}) vs ALLOW INR {allow_total:.0f} / ASK INR {ask_total:.0f} / DENY INR {deny_total:.0f}."

    # Also surface what the deterministic DecisionEngine already decided
    if decision_result:
        det = decision_result.get("decision")
        if det and det != recommended:
            reason += f" Deterministic engine said {det}; simulator agrees on cost but safety prefers {recommended} when violation exists."

    result = {
        "counterfactuals": [c.__dict__ for c in counterfactuals],
        "recommended": recommended,
        "reason": reason,
        "disclaimer": "SIMULATED / ESTIMATED — derived from synthetic cost model, not real financial forecast",
        "inputs": {"amount": amount, "risk_score": risk_score, "p_fraud": round(p_fraud, 3), "violations": violations},
    }
    logger.info(f"Simulator amount={amount} risk={risk_score} p_fraud={p_fraud:.2f} recommended={recommended}")
    return result


def to_table(counterfactuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Helper for UI table rendering."""
    return [
        {
            "Action": c["action"],
            "Fraud Exposure (SIM)": f"INR {c['fraud_exposure']:.0f}",
            "FP Cost (SIM)": f"INR {c['false_positive_cost']:.0f}",
            "Ops Cost (SIM)": f"INR {c['operational_cost']:.0f}",
            "Friction": c["customer_friction"],
            "Total (SIM)": f"INR {c['expected_total_cost']:.0f}",
            "Policy": "VIOLATION" if c["policy_violation"] else "ok",
        }
        for c in counterfactuals
    ]
