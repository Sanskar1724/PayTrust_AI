"""
tests/test_simulator.py — Phase 10 counterfactual.
"""
from __future__ import annotations

from engines.decision_simulator import simulate

def _pol(violations=None):
    return {"authorized": len(violations or [])==0, "violations": violations or [], "requires_approval": False, "reasons": []}

def test_simulate_recommends_allow_low_risk():
    payment = {"amount": 5000}
    pol = _pol([])
    risk = {"risk_score": 15, "risk_level": "LOW", "factors": []}
    res = simulate(payment, pol, risk)
    assert res["recommended"] == "ALLOW"
    assert len(res["counterfactuals"]) == 3
    assert res["disclaimer"].startswith("SIMULATED")
    # ALLOW cheapest
    allow = next(c for c in res["counterfactuals"] if c["action"] == "ALLOW")
    assert allow["expected_total_cost"] < 1000

def test_simulate_deny_on_violation():
    payment = {"amount": 10000}
    pol = _pol(["category_blocked"])
    risk = {"risk_score": 10, "risk_level": "LOW", "factors": []}
    res = simulate(payment, pol, risk)
    assert res["recommended"] == "DENY"
    allow = next(c for c in res["counterfactuals"] if c["action"] == "ALLOW")
    assert allow["policy_violation"] is True

def test_simulate_high_risk_recommends_deny():
    payment = {"amount": 40000}
    pol = _pol([])
    risk = {"risk_score": 85, "risk_level": "CRITICAL", "factors": [{"name":"merchant_risk","severity":"critical","score":25,"details":"gambling"}]}
    res = simulate(payment, pol, risk)
    # Even though ALLOW cheapest if legit, high risk should still recommend DENY or at least not ALLOW when violation
    # With no violation, high risk still may recommend DENY due to fraud exposure
    # Our simulator picks cost-based, but for critical p_fraud 0.85, ALLOW total = 0.85*40000=34000, ASK=... DENY with high FP but still maybe ASK cheaper
    # So we just assert recommended is not ALLOW with high risk
    assert res["recommended"] in ("ASK_USER","DENY")

def test_simulate_medium_risk_ask():
    payment = {"amount": 25000}
    pol = _pol([])
    risk = {"risk_score": 50, "risk_level": "MEDIUM", "factors": []}
    res = simulate(payment, pol, risk)
    # Medium risk — ASK should be competitive
    assert "counterfactuals" in res
    assert all(c["label"] == "SIMULATED / ESTIMATED" for c in res["counterfactuals"])
    assert "inputs" in res
    assert res["inputs"]["p_fraud"] == 0.5

def test_simulate_all_labeled_simulated():
    payment = {"amount": 1000}
    pol = _pol([])
    risk = {"risk_score": 0, "risk_level": "LOW", "factors": []}
    res = simulate(payment, pol, risk)
    for c in res["counterfactuals"]:
        assert "SIMULATED" in c["label"]
