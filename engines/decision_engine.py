"""
engines/decision_engine.py — Phase 6 Decision Engine.

Combines deterministic PolicyEngine + RiskEngine into a final decision.
LLM never overrides — this is the enforcement layer.

Decisions: ALLOW | ASK_USER | DENY

Documented thresholds (no magic):
  POLICY_VIOLATION           → DENY  (even if risk LOW)
  risk_level CRITICAL/HIGH   → DENY  (even if policy passes, high risk is unsafe)
  risk_level MEDIUM + policy pass → ASK_USER
  risk_level LOW + policy pass    → ALLOW
  policy requires_approval + LOW risk → ASK_USER (approval gate)

Uses risk_thresholds from config for level mapping, but decision boundaries are explicit below.
Stores reasons for audit.
"""
from __future__ import annotations

from typing import Any

from core.config import get_settings
from core.exceptions import DecisionEngineError
from core.logger import get_logger
from engines.policy_engine import PolicyEngine
from engines.risk_engine import RiskEngine

logger = get_logger("engines.decision")
settings = get_settings()


class DecisionEngine:
    def __init__(self, policy_engine: PolicyEngine | None = None, risk_engine: RiskEngine | None = None):
        self.policy_engine = policy_engine or PolicyEngine()
        self.risk_engine = risk_engine or RiskEngine()

    def decide(
        self,
        policy_result: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Pure decision — no DB.

        Inputs:
          policy_result: {authorized, requires_approval, violations, reasons}
          risk_result: {risk_score, risk_level, factors}

        Returns:
          {
            "decision": "ALLOW"|"ASK_USER"|"DENY",
            "risk_score": int,
            "risk_level": str,
            "policy_result": {...},
            "risk_result": {...},
            "reasons": [str],
            "requires_approval": bool
          }
        """
        if not isinstance(policy_result, dict) or not isinstance(risk_result, dict):
            raise DecisionEngineError("policy_result and risk_result dicts required")

        authorized: bool = bool(policy_result.get("authorized", False))
        violations: list[str] = policy_result.get("violations", []) or []
        requires_approval: bool = bool(policy_result.get("requires_approval", False))
        risk_score: int = int(risk_result.get("risk_score", 0))
        risk_level: str = str(risk_result.get("risk_level", "LOW")).upper()
        factors: list[dict] = risk_result.get("factors", [])

        reasons: list[str] = []

        # 1. Policy violation is an immediate DENY — deterministic safety
        if not authorized:
            decision = "DENY"
            reasons.append(f"Policy violation: {', '.join(violations) if violations else 'unauthorized'}")
            reasons.extend(policy_result.get("reasons", [])[:2])
            # Add risk context
            if risk_level in ("HIGH", "CRITICAL"):
                reasons.append(f"Risk is {risk_level} ({risk_score}) — reinforces DENY")
            logger.info(f"Decision DENY (policy violation) risk={risk_score} violations={violations}")
            return self._pack(decision, risk_score, risk_level, policy_result, risk_result, reasons, requires_approval)

        # 2. High / Critical risk → DENY even if policy passes (safety)
        if risk_level in ("HIGH", "CRITICAL"):
            decision = "DENY"
            top = factors[0] if factors else {}
            reasons.append(f"High risk: {risk_level} ({risk_score}) — top factor {top.get('name','unknown')} ({top.get('severity','')})")
            reasons.append("Deterministic safety: high risk transactions are denied even when policy passes")
            if requires_approval:
                reasons.append("Would also require approval, but risk overrides to DENY")
            logger.info(f"Decision DENY (high risk) score={risk_score}")
            return self._pack(decision, risk_score, risk_level, policy_result, risk_result, reasons, requires_approval)

        # 3. Medium risk → ASK_USER (even if policy allows)
        if risk_level == "MEDIUM":
            decision = "ASK_USER"
            reasons.append(f"Medium risk ({risk_score}) — policy passes but verification recommended")
            if requires_approval:
                reasons.append("Policy requires approval for this amount — ASK_USER aligns with policy")
            if factors:
                reasons.append(f"Top risk factor: {factors[0].get('name')} ({factors[0].get('severity')})")
            return self._pack(decision, risk_score, risk_level, policy_result, risk_result, reasons, requires_approval)

        # 4. Low risk + policy pass
        #    If policy says requires_approval, escalate to ASK_USER instead of ALLOW
        if risk_level == "LOW":
            if requires_approval:
                decision = "ASK_USER"
                reasons.append(f"Low risk ({risk_score}) but amount exceeds approval threshold — ASK_USER per policy")
            else:
                decision = "ALLOW"
                reasons.append(f"Low risk ({risk_score}) and policy passes — ALLOW")
            return self._pack(decision, risk_score, risk_level, policy_result, risk_result, reasons, requires_approval)

        # Fallback — unknown level
        decision = "ASK_USER"
        reasons.append(f"Unknown risk level '{risk_level}' — default to ASK_USER for safety")
        return self._pack(decision, risk_score, risk_level, policy_result, risk_result, reasons, requires_approval)

    def decide_for_request(
        self,
        payment: dict[str, Any],
        policy_result: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Convenience: runs RiskEngine.assess then decide.
        """
        risk_result = self.risk_engine.assess(payment, policy_result=policy_result, context=context)
        return self.decide(policy_result, risk_result)

    def _pack(self, decision: str, risk_score: int, risk_level: str, policy_result: dict, risk_result: dict, reasons: list[str], requires_approval: bool) -> dict[str, Any]:
        return {
            "decision": decision,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "policy_result": policy_result,
            "risk_result": risk_result,
            "reasons": reasons,
            "requires_approval": requires_approval,
        }
