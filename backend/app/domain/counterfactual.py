"""Counterfactual simulator: what would ALLOW / ASK_USER / DENY each cost?

All money figures are SIMULATED estimates from the configurable cost model — never a
forecast. A policy violation always forces DENY regardless of cost.
"""
from __future__ import annotations

from typing import Any

from app.config import get_settings

ASK_FRAUD_RESIDUAL = 0.4    # review catches ~60% of fraud
ASK_FRICTION_SHARE = 0.3    # ~30% of legit users feel the friction cost
DENY_FRAUD_RESIDUAL = 0.05  # blocking stops ~95% of fraud
OPS_COST = {"ALLOW": 0.0, "ASK_USER": 250.0, "DENY": 120.0}
DISCLAIMER = "SIMULATED / ESTIMATED — derived from a configurable cost model, not a financial forecast"


def simulate(payment: dict[str, Any], policy_result: dict[str, Any], risk_result: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    amount = int(payment.get("amount") or 0)
    risk_score = int(risk_result.get("risk_score") or 0)
    violations = list(policy_result.get("violations") or [])

    p_fraud = max(0.0, min(1.0, risk_score / 100.0))
    if risk_score == 0 and not violations:
        p_fraud = 0.02

    fp_unit = (
        s.FP_CUSTOMER_FRICTION_COST
        + s.FP_SUPPORT_COST
        + s.FP_MERCHANT_IMPACT_COST
        + amount * s.FP_LOST_TRANSACTION_VALUE_MULTIPLIER * 0.1
    )
    fn_unit = amount * s.FN_FRAUD_EXPOSURE_MULTIPLIER

    rows = [
        ("ALLOW", p_fraud * fn_unit, 0.0, "low", "No friction, full exposure if this is fraud"),
        ("ASK_USER", p_fraud * fn_unit * ASK_FRAUD_RESIDUAL, (1 - p_fraud) * fp_unit * ASK_FRICTION_SHARE, "medium",
         "Review balances fraud against friction"),
        ("DENY", p_fraud * fn_unit * DENY_FRAUD_RESIDUAL, (1 - p_fraud) * fp_unit, "high",
         "Safest against fraud, costly if the payment was legitimate"),
    ]
    counterfactuals = []
    for action, fraud, fp, friction, rationale in rows:
        ops = OPS_COST[action]
        counterfactuals.append({
            "action": action,
            "fraud_exposure": round(fraud, 2),
            "false_positive_cost": round(fp, 2),
            "operational_cost": ops,
            "customer_friction": friction,
            "expected_total_cost": round(fraud + fp + ops, 2),
            "allowed_by_policy": not (violations and action == "ALLOW"),
            "rationale": rationale,
        })

    if violations:
        recommended = "DENY"
        reason = f"Policy violation ({', '.join(violations[:2])}) forces DENY regardless of cost."
    else:
        best = min(counterfactuals, key=lambda c: c["expected_total_cost"])
        recommended = best["action"]
        reason = f"{recommended} has the lowest simulated expected cost (INR {best['expected_total_cost']:,.0f})."

    return {
        "counterfactuals": counterfactuals,
        "recommended": recommended,
        "reason": reason,
        "p_fraud": round(p_fraud, 3),
        "disclaimer": DISCLAIMER,
    }
