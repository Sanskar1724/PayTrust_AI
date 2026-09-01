"""
tests/test_decision_engine.py — Phase 6 decision boundaries.
"""
from __future__ import annotations

import pytest
from engines.decision_engine import DecisionEngine

@pytest.fixture
def engine():
    return DecisionEngine()

def _pol(auth=True, violations=None, requires=False):
    return {"authorized": auth, "violations": violations or [], "requires_approval": requires, "reasons": []}

def _risk(score, level, factors=None):
    return {"risk_score": score, "risk_level": level, "factors": factors or [{"name": "test", "severity": "low", "score": 5, "details": "test"}]}

def test_allow_low_risk_policy_pass(engine):
    dec = engine.decide(_pol(True, [], False), _risk(15, "LOW"))
    assert dec["decision"] == "ALLOW"
    assert dec["risk_score"] == 15

def test_ask_user_medium_risk_policy_pass(engine):
    dec = engine.decide(_pol(True, [], False), _risk(45, "MEDIUM"))
    assert dec["decision"] == "ASK_USER"

def test_ask_user_low_risk_requires_approval(engine):
    dec = engine.decide(_pol(True, [], True), _risk(20, "LOW"))
    assert dec["decision"] == "ASK_USER"

def test_deny_high_risk_even_if_policy_pass(engine):
    dec = engine.decide(_pol(True, [], False), _risk(75, "HIGH"))
    assert dec["decision"] == "DENY"

def test_deny_critical_risk(engine):
    dec = engine.decide(_pol(True, [], False), _risk(90, "CRITICAL"))
    assert dec["decision"] == "DENY"

def test_deny_policy_violation_low_risk(engine):
    dec = engine.decide(_pol(False, ["category_blocked"], False), _risk(10, "LOW"))
    assert dec["decision"] == "DENY"

def test_deny_policy_violation_high_risk(engine):
    dec = engine.decide(_pol(False, ["max_transaction_exceeded"], False), _risk(80, "HIGH"))
    assert dec["decision"] == "DENY"

def test_ask_user_medium_requires_approval(engine):
    dec = engine.decide(_pol(True, [], True), _risk(50, "MEDIUM"))
    assert dec["decision"] == "ASK_USER"

def test_boundary_low_30_is_low(engine):
    dec = engine.decide(_pol(True, [], False), _risk(30, "LOW"))
    assert dec["decision"] == "ALLOW"

def test_boundary_medium_60(engine):
    dec = engine.decide(_pol(True, [], False), _risk(60, "MEDIUM"))
    assert dec["decision"] == "ASK_USER"

def test_boundary_high_80(engine):
    dec = engine.decide(_pol(True, [], False), _risk(80, "HIGH"))
    assert dec["decision"] == "DENY"

def test_reasons_stored(engine):
    dec = engine.decide(_pol(False, ["daily_limit_exceeded"], False), _risk(10, "LOW"))
    assert len(dec["reasons"]) >= 1
    assert "daily_limit_exceeded" in dec["reasons"][0] or "Policy violation" in dec["reasons"][0]

def test_decide_for_request_convenience(engine):
    payment = {"amount": 25000, "category": "books"}
    pol = _pol(True, [], False)
    dec = engine.decide_for_request(payment, pol, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 1, "user_total_txns": 10})
    assert dec["decision"] in ("ALLOW","ASK_USER","DENY")
    assert "risk_score" in dec
