"""Pure engine tests (ported from v1 and extended). No database."""
from __future__ import annotations

import pytest

from app.domain.counterfactual import simulate
from app.domain.decision import decide
from app.domain.explain import build_facts, deterministic_explanation
from app.domain.policy import DEFAULT_RULES, evaluate_policy
from app.domain.risk import assess_risk, level_for
from app.errors import ValidationFailed


def pay(**kw):
    return {"amount": 25_000, "category": "electronics", "merchant_id": 1, "merchant_name": "TechMart"} | kw


# ── Policy ──

@pytest.mark.parametrize("payment, spent, violation", [
    (pay(amount=65_000), 0, "max_transaction_exceeded"),
    (pay(category="gambling"), 0, "category_blocked"),
    (pay(category="fashion"), 0, "category_not_allowed"),
    (pay(amount=30_000), 80_000, "daily_limit_exceeded"),
    (pay(amount=0), 0, "invalid_amount"),
    (pay(category=""), 0, "missing_category"),
    (pay(category="electronics", merchant_category="gambling"), 0, "merchant_category_blocked"),
])
def test_policy_violations(payment, spent, violation):
    result = evaluate_policy(DEFAULT_RULES, payment, spent)
    assert violation in result["violations"]
    assert result["authorized"] is False


def test_policy_within_limits():
    result = evaluate_policy(DEFAULT_RULES, pay(amount=25_000), 0)
    assert result == result | {"authorized": True, "requires_approval": False, "violations": []}


def test_policy_approval_threshold_is_not_a_violation():
    result = evaluate_policy(DEFAULT_RULES, pay(amount=45_000), 0)
    assert result["authorized"] and result["requires_approval"]


def test_policy_daily_limit_boundary_is_inclusive():
    assert evaluate_policy(DEFAULT_RULES, pay(amount=20_000), 80_000)["authorized"]
    assert not evaluate_policy(DEFAULT_RULES, pay(amount=20_001), 80_000)["authorized"]


def test_policy_missing_and_preconditions():
    assert evaluate_policy(None, pay())["violations"] == ["missing_policy"]
    result = evaluate_policy(DEFAULT_RULES, pay(), 0, [("missing_user", "no user")])
    assert result["violations"] == ["missing_user"] and not result["authorized"]


def test_policy_merchant_lists_and_inactive():
    rules = {**DEFAULT_RULES.summary(), "blocked_merchants": ["TechMart"], "is_active": False}
    v = evaluate_policy(rules, pay(), 0)["violations"]
    assert "merchant_blocked" in v and "agent_unauthorized" in v
    allow_only = {**DEFAULT_RULES.summary(), "allowed_merchants": ["2"]}
    assert "merchant_not_allowed" in evaluate_policy(allow_only, pay(), 0)["violations"]
    assert evaluate_policy(allow_only, pay(merchant_id=2, merchant_name="Other"), 0)["authorized"]


# ── Risk ──

def test_risk_low_for_normal_payment():
    r = assess_risk(pay(amount=5_000), {"violations": []}, {"daily_limit": 100_000, "user_total_txns": 20})
    assert r["risk_level"] == "LOW" and r["risk_score"] <= 30


def test_risk_critical_category_floor():
    r = assess_risk(pay(category="gambling", amount=1_000))
    assert r["risk_score"] >= 65 and r["factors"][0]["severity"] == "critical"


def test_risk_is_deterministic_and_capped():
    args = (pay(amount=90_000, category="gambling"),
            {"violations": ["max_transaction_exceeded", "category_blocked", "daily_limit_exceeded", "unauthorized_agent"]},
            {"daily_limit": 100_000, "daily_spent": 95_000, "transactions_last_hour": 20, "is_new_user": True})
    assert assess_risk(*args) == assess_risk(*args)
    assert assess_risk(*args)["risk_score"] == 100


def test_risk_frequency_and_duplicates():
    base = {"daily_limit": 100_000, "user_total_txns": 50}
    assert any(f["name"] == "frequency_risk" for f in assess_risk(pay(amount=1_000), None, base | {"transactions_last_hour": 10})["factors"])
    one = assess_risk(pay(amount=1_000), None, base | {"duplicates_recent": 1})
    many = assess_risk(pay(amount=1_000), None, base | {"duplicates_recent": 3})
    assert one["risk_level"] == "MEDIUM"
    assert many["risk_level"] in ("HIGH", "CRITICAL")


def test_risk_category_mismatch():
    r = assess_risk(pay(category="electronics", merchant_category="books"))
    assert any(f["name"] == "category_mismatch" for f in r["factors"])


def test_risk_rejects_bad_amount():
    with pytest.raises(ValidationFailed):
        assess_risk(pay(amount=-5))


@pytest.mark.parametrize("score, level", [(0, "LOW"), (30, "LOW"), (31, "MEDIUM"), (60, "MEDIUM"),
                                          (61, "HIGH"), (80, "HIGH"), (81, "CRITICAL")])
def test_risk_level_boundaries(score, level):
    assert level_for(score) == level


# ── Decision ──

def _p(authorized=True, approval=False, violations=None):
    return {"authorized": authorized, "requires_approval": approval, "violations": violations or [], "reasons": ["r"]}


def _r(score, level):
    return {"risk_score": score, "risk_level": level, "factors": [{"name": "x", "severity": "low", "score": 1, "details": "d"}]}


@pytest.mark.parametrize("policy, risk, expected", [
    (_p(), _r(10, "LOW"), "ALLOW"),
    (_p(approval=True), _r(10, "LOW"), "ASK_USER"),
    (_p(), _r(45, "MEDIUM"), "ASK_USER"),
    (_p(), _r(70, "HIGH"), "DENY"),
    (_p(), _r(95, "CRITICAL"), "DENY"),
    (_p(False, violations=["category_blocked"]), _r(5, "LOW"), "DENY"),
    (_p(True, violations=["x"]), _r(5, "LOW"), "DENY"),  # violations always win, even if flagged authorized
])
def test_decision_matrix(policy, risk, expected):
    assert decide(policy, risk)["decision"] == expected


def test_any_violation_always_denies():
    for level, score in (("LOW", 0), ("MEDIUM", 50), ("HIGH", 70)):
        assert decide(_p(False, violations=["daily_limit_exceeded"]), _r(score, level))["decision"] == "DENY"


# ── Counterfactuals + explanation ──

def test_simulator_forces_deny_on_violation():
    sim = simulate(pay(), {"violations": ["category_blocked"]}, {"risk_score": 10})
    assert sim["recommended"] == "DENY"
    assert next(c for c in sim["counterfactuals"] if c["action"] == "ALLOW")["allowed_by_policy"] is False


def test_simulator_low_risk_prefers_allow_and_costs_non_negative():
    sim = simulate(pay(amount=2_000), {"violations": []}, {"risk_score": 5})
    assert sim["recommended"] == "ALLOW"
    assert all(c["expected_total_cost"] >= 0 for c in sim["counterfactuals"])
    assert "SIMULATED" in sim["disclaimer"]


def test_deterministic_explanation_uses_only_facts():
    policy = evaluate_policy(DEFAULT_RULES, pay(category="gambling"), 0)
    risk = assess_risk(pay(category="gambling"), policy)
    facts = build_facts(pay(category="gambling", request_id="r1"), policy, risk, decide(policy, risk))
    out = deterministic_explanation(facts)
    assert "category_blocked" in out["explanation"]
    assert "DENY" in out["explanation"]
    assert 0 <= out["confidence"] <= 1
