# DECISION_ENGINE.md — Phase 6 & 10

## Purpose
Deterministically combine `PolicyEngine` + `RiskEngine` into a final `ALLOW / ASK_USER / DENY` that is **enforceable, explainable, and auditable**. LLM never overrides.

## Inputs

- `policy_result: {authorized: bool, requires_approval: bool, violations: [str], reasons: [str]}` from `engines/policy_engine.py:73`
- `risk_result: {risk_score: 0-100, risk_level: LOW/MEDIUM/HIGH/CRITICAL, factors: [{name, severity, score}]}` from `engines/risk_engine.py:1`

## Thresholds (Documented, from `core/config.py:56`)

```
LOW      ≤30
MEDIUM   ≤60
HIGH     ≤80
CRITICAL >80
```

No magic numbers in `engines/decision_engine.py:18`.

## Rules (in order, `engines/decision_engine.py:18`)

1. **POLICY_VIOLATION → DENY** — even if `risk_level == LOW`. Reason includes `violations` list. Example: `category_blocked` → DENY.
2. **HIGH / CRITICAL → DENY** — even if policy passes. High risk is unsafe to auto-allow. Includes top factor.
3. **MEDIUM → ASK_USER** — policy passes but verification recommended. If `requires_approval`, notes alignment.
4. **LOW + requires_approval → ASK_USER** — amount exceeds `approval_threshold` (30k), escalate.
5. **LOW + pass → ALLOW** — no violation, low risk, no approval needed.

Fallback: unknown level → `ASK_USER` for safety.

## outputs

```python
{
  "decision": "ALLOW" | "ASK_USER" | "DENY",
  "risk_score": 42,
  "risk_level": "MEDIUM",
  "policy_result": {...},
  "risk_result": {...},
  "reasons": ["Medium risk (45) — policy passes but verification recommended", ...],
  "requires_approval": False
}
```

Stored in `decisions` table (`database/database.py:97`) with `policy_result` JSON and `reasons` array for audit.

## Counterfactual Simulator (Phase 10)

`engines/decision_simulator.py:1` re-evaluates the same payment under 3 actions:

- **ALLOW** — low friction, full fraud exposure `p_fraud * amount`
- **ASK_USER** — mitigates 60% fraud, 30% FP cost, ops 250
- **DENY** — mitigates 95% fraud, full FP cost, ops 120

`p_fraud = risk_score/100`. Costs use `settings.FP_*` / `FN_*` (SIMULATED assumptions). Hard guard: if violation, `ALLOW` is disallowed → `DENY` recommended. Recommended is `min(expected_total_cost)` plus safety.

All numbers labeled **SIMULATED / ESTIMATED** (`engines/decision_simulator.py:65` disclaimer).

## Testing

`tests/test_decision_engine.py:1` covers every boundary:

- `ALLOW` LOW+pass, `ASK` MEDIUM, `ASK` LOW+approval, `DENY` HIGH even if pass, `DENY` violation even if LOW, thresholds 30/60/80, reasons stored, `decide_for_request` convenience.

`tests/test_simulator.py:1` covers counterfactuals.

## Example

- Payment: INR 25k electronics, policy pass, risk LOW 15 → `ALLOW` (`engines/decision_engine.py:decide`)
- Same but amount 35k (requires_approval) → `ASK_USER`
- Same but risk HIGH 75 → `DENY` even though policy passes
- Same but category gambling → `DENY` (violation) with `reasons: ["Policy violation: category_blocked"]`
