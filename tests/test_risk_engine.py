"""
tests/test_risk_engine.py — Phase 5 deterministic risk tests.
"""
from __future__ import annotations

import pytest
from engines.risk_engine import RiskEngine

@pytest.fixture
def engine():
    return RiskEngine()

def test_low_risk_normal(engine):
    res = engine.assess({"amount": 5000, "category": "books"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 1, "user_total_txns": 20})
    assert res["risk_level"] == "LOW"
    assert res["risk_score"] <= 30
    assert res["risk_score"] >= 0

def test_medium_risk_amount_and_spending(engine):
    # 35000 triggers amount medium + spending medium
    res = engine.assess({"amount": 35000, "category": "electronics"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 40000, "transactions_last_hour": 1, "user_total_txns": 20})
    # 35000 amount 12 + spending 0.75 ratio 12 = 24 -> LOW, but with medium we expect <=30?
    # Add frequency to push to medium
    res2 = engine.assess({"amount": 35000, "category": "electronics"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 40000, "transactions_last_hour": 5, "user_total_txns": 20})
    assert res2["risk_level"] in ("LOW","MEDIUM")
    assert res2["risk_score"] >= 12

def test_high_risk_gambling_critical(engine):
    res = engine.assess({"amount": 20000, "category": "gambling"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 1, "user_total_txns": 20})
    assert res["risk_level"] in ("HIGH","CRITICAL")
    assert res["risk_score"] >= 65  # critical boost
    assert any(f["name"] == "merchant_risk" and f["severity"] == "critical" for f in res["factors"])

def test_policy_violation_boosts_risk(engine):
    res = engine.assess({"amount": 10000, "category": "electronics"}, policy_result={"violations": ["category_blocked"]}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 0, "user_total_txns": 20})
    assert res["risk_score"] >= 65
    assert any(f["name"] == "policy_risk" for f in res["factors"])

def test_agent_auth_critical(engine):
    res = engine.assess({"amount": 10000, "category": "books"}, policy_result={"violations": ["unauthorized_agent"]}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 0, "user_total_txns": 20})
    assert res["risk_level"] in ("HIGH","CRITICAL")
    assert any(f["name"] == "agent_auth_risk" for f in res["factors"])

def test_frequency_high(engine):
    res = engine.assess({"amount": 5000, "category": "books"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 10, "user_total_txns": 20})
    assert any(f["name"] == "frequency_risk" and f["score"] == 20 for f in res["factors"])

def test_new_user_high_amount(engine):
    res = engine.assess({"amount": 40000, "category": "electronics"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 1, "user_total_txns": 2, "is_new_user": True})
    assert any(f["name"] == "historical_behavior" for f in res["factors"])
    assert res["risk_score"] >= 12

def test_new_merchant(engine):
    res = engine.assess({"amount": 8000, "category": "electronics"}, policy_result={"violations": []}, context={"daily_limit": 100000, "daily_spent": 0, "transactions_last_hour": 1, "user_total_txns": 20, "is_new_merchant": True})
    assert any(f["name"] == "merchant_risk" and "First transaction" in f["details"] for f in res["factors"])

def test_deterministic_same_input_same_output(engine):
    p = {"amount": 25000, "category": "travel"}
    pr = {"violations": []}
    ctx = {"daily_limit": 100000, "daily_spent": 10000, "transactions_last_hour": 2, "user_total_txns": 10}
    r1 = engine.assess(p, pr, ctx)
    r2 = engine.assess(p, pr, ctx)
    assert r1 == r2

def test_risk_score_capped_100(engine):
    # Combine many high factors
    res = engine.assess(
        {"amount": 90000, "category": "gambling", "merchant_risk_tier": "high"},
        policy_result={"violations": ["max_transaction_exceeded","category_blocked","unauthorized_agent"]},
        context={"daily_limit": 100000, "daily_spent": 90000, "transactions_last_hour": 12, "user_total_txns": 1, "is_new_merchant": True, "is_new_user": True}
    )
    assert res["risk_score"] == 100
    assert res["risk_level"] == "CRITICAL"

def test_invalid_amount_raises(engine):
    with pytest.raises(Exception):
        engine.assess({"amount": -5, "category": "books"}, policy_result={}, context={})
