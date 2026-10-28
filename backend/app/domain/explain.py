"""Structured facts for the AI investigator + the deterministic explanation fallback."""
from __future__ import annotations

from typing import Any


def build_facts(payment: dict[str, Any], policy_result: dict[str, Any], risk_result: dict[str, Any],
                decision: dict[str, Any]) -> dict[str, Any]:
    """The ONLY input the LLM sees: engine outputs, no raw PII beyond ids."""
    return {
        "transaction": {
            "request_id": payment.get("request_id"),
            "amount_inr": payment.get("amount"),
            "category": payment.get("category"),
            "merchant": payment.get("merchant_name"),
            "merchant_registered_category": payment.get("merchant_category"),
            "user_id": payment.get("user_id"),
            "agent_id": payment.get("agent_id"),
            "description": payment.get("description"),
            "agent_reason": payment.get("agent_reason"),
        },
        "policy_result": {
            "authorized": policy_result.get("authorized"),
            "requires_approval": policy_result.get("requires_approval"),
            "violations": policy_result.get("violations") or [],
            "reasons": (policy_result.get("reasons") or [])[:4],
            "limits": policy_result.get("policy"),
            "spent_today_before_this": policy_result.get("daily_spent"),
        },
        "risk_result": {
            "risk_score": risk_result.get("risk_score"),
            "risk_level": risk_result.get("risk_level"),
            "factors": (risk_result.get("factors") or [])[:5],
        },
        "decision": {
            "decision": decision.get("decision"),
            "reasons": (decision.get("reasons") or [])[:3],
        },
    }


def deterministic_explanation(facts: dict[str, Any]) -> dict[str, Any]:
    """Rule-based explanation built strictly from facts — used offline or when every LLM fails."""
    pol = facts.get("policy_result") or {}
    risk = facts.get("risk_result") or {}
    decision = (facts.get("decision") or {}).get("decision", "UNKNOWN")
    violations: list[str] = pol.get("violations") or []
    factors: list[dict] = risk.get("factors") or []
    level, score = risk.get("risk_level", "LOW"), risk.get("risk_score", 0)

    parts = [f"Policy violations: {', '.join(violations)}." if violations else "No policy violations."]
    if factors:
        top = factors[0]
        parts.append(f"Strongest risk signal: {top.get('details')} ({top.get('severity')}, +{top.get('score')}).")
    parts.append(f"The engines decided {decision} at {level} risk ({score}).")

    concerns = [f"{f.get('name')}: {f.get('details')}" for f in factors[:3] if f.get("severity") in ("high", "critical")]
    if not concerns:
        concerns = ["No strong concerns beyond the listed factors."]

    questions = {
        "ASK_USER": ["Did the user ask the agent to make this purchase?", "Is this merchant and amount normal for this user?"],
        "DENY": ["Is the policy limit right for this user and agent?", "Could the agent have been manipulated into this request?"],
    }.get(decision, ["Is the agent authorized for this category?", "Does recent history show anything unusual?"])

    if level in ("HIGH", "CRITICAL") and violations:
        confidence = 0.88
    elif not violations and level in ("HIGH", "CRITICAL"):
        confidence = 0.55
    elif level == "MEDIUM":
        confidence = 0.72
    else:
        confidence = 0.65

    return {
        "explanation": " ".join(parts),
        "summary": f"{decision} at {level} ({score})" + (f" — {', '.join(violations)}" if violations else " — policy passes"),
        "concerns": concerns,
        "review_questions": questions,
        "confidence": confidence,
    }
