"""ALLOW / ASK_USER / DENY — hard rules, evaluated in order:

  1. any policy violation        → DENY
  2. HIGH or CRITICAL risk       → DENY
  3. MEDIUM risk                 → ASK_USER
  4. LOW risk + approval needed  → ASK_USER
  5. LOW risk                    → ALLOW
"""
from __future__ import annotations

from typing import Any

ALLOW, ASK_USER, DENY = "ALLOW", "ASK_USER", "DENY"


def decide(policy_result: dict[str, Any], risk_result: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = policy_result.get("violations") or []
    authorized = bool(policy_result.get("authorized")) and not violations
    requires_approval = bool(policy_result.get("requires_approval"))
    score = int(risk_result.get("risk_score", 0))
    level = str(risk_result.get("risk_level", "LOW")).upper()
    factors: list[dict] = risk_result.get("factors") or []
    top = factors[0] if factors else None
    reasons: list[str] = []

    if not authorized:
        decision = DENY
        reasons.append(f"Policy violation: {', '.join(violations) or 'unauthorized'}.")
        reasons.extend((policy_result.get("reasons") or [])[:2])
        if level in ("HIGH", "CRITICAL"):
            reasons.append(f"Risk is also {level} ({score}).")
    elif level in ("HIGH", "CRITICAL"):
        decision = DENY
        reasons.append(f"{level.title()} risk ({score})" + (f" — top factor: {top['details']}." if top else "."))
        reasons.append("High-risk payments are denied even when policy passes.")
    elif level == "MEDIUM":
        decision = ASK_USER
        reasons.append(f"Medium risk ({score}) — the user should confirm.")
        if top:
            reasons.append(f"Top factor: {top['details']}.")
        if requires_approval:
            reasons.append("The amount is also above the approval threshold.")
    elif level == "LOW" and requires_approval:
        decision = ASK_USER
        reasons.append(f"Low risk ({score}), but the amount is above the approval threshold.")
    elif level == "LOW":
        decision = ALLOW
        reasons.append(f"Low risk ({score}) and within policy.")
    else:
        decision = ASK_USER
        reasons.append(f"Unknown risk level '{level}' — asking the user to be safe.")

    return {
        "decision": decision,
        "risk_score": score,
        "risk_level": level,
        "reasons": reasons,
        "requires_approval": requires_approval,
    }
