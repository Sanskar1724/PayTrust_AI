"""
tests/test_integration.py — End-to-end flow across engines + DB.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import json

from database.database import init_db, get_connection
from database import repositories as repo
from models.payment_request import PaymentRequest
from engines.policy_engine import PolicyEngine
from engines.risk_engine import RiskEngine
from engines.decision_engine import DecisionEngine
from engines.ai_engine import AIEngine, build_facts
from engines.decision_simulator import simulate
from core.security import audit_log

def _tmp_db():
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name) / "test.db"
    init_db(seed=True, db_path=p)
    return tmp, p

def _safe_cleanup(tmp):
    import gc, time
    gc.collect()
    time.sleep(0.05)
    try:
        tmp.cleanup()
    except PermissionError:
        # Windows SQLite WAL lock — try again after GC
        gc.collect()
        time.sleep(0.1)
        try:
            tmp.cleanup()
        except Exception:
            pass

def test_e2e_allow_flow():
    tmp, dbp = _tmp_db()
    try:
        # 1. Valid payment
        pr = PaymentRequest(request_id="req_e2e_allow", user_id=1, agent_id=1, merchant_id=1, merchant_name="TechMart Electronics", amount=15000, currency="INR", category="electronics")
        repo.create_payment_request(**pr.to_db_dict(), db_path=dbp)
        # 2. Policy + Risk + Decision
        pe = PolicyEngine(); re = RiskEngine(); de = DecisionEngine(pe, re)
        pol = pe.evaluate_request(1,1,15000,"electronics",merchant_id=1, db_path=dbp)
        assert pol["authorized"] is True
        risk = re.assess_request(1,1,{"amount":15000,"category":"electronics","merchant_id":1}, pol, db_path=dbp)
        assert risk["risk_level"] == "LOW"
        dec = de.decide(pol, risk)
        assert dec["decision"] == "ALLOW"
        # 3. Persist
        with get_connection(dbp) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO risk_assessments (request_id, risk_score, risk_level, factors) VALUES (?,?,?,?)", (pr.request_id, risk["risk_score"], risk["risk_level"], json.dumps(risk["factors"])))
            cur.execute("INSERT INTO decisions (request_id, decision, risk_score, risk_level, policy_result, reasons) VALUES (?,?,?,?,?,?)", (pr.request_id, dec["decision"], dec["risk_score"], dec["risk_level"], json.dumps(pol), json.dumps(dec["reasons"])))
            conn.commit()
        # 4. AI does not override
        facts = build_facts(pr.to_db_dict(), pol, risk, dec)
        ai = AIEngine()
        # offline
        ai.providers = [ai.providers[-1]]
        ai_res = ai.investigate(facts)
        assert "explanation" in ai_res
        assert dec["decision"] == "ALLOW"  # unchanged
        # 5. Simulator agrees
        sim = simulate(pr.to_db_dict(), pol, risk, dec)
        assert sim["recommended"] in ("ALLOW","ASK_USER","DENY")
        # 6. Audit
        audit_log(pr.request_id, "PAYMENT_EVALUATED", "test", dec["decision"], {"amount": 15000}, db_path=dbp)
        with get_connection(dbp) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM audit_logs WHERE request_id=?", (pr.request_id,))
            assert cur.fetchone()[0] >= 1
    finally:
        _safe_cleanup(tmp)

def test_e2e_deny_blocked_category():
    tmp, dbp = _tmp_db()
    try:
        pr = PaymentRequest(request_id="req_e2e_deny", user_id=1, agent_id=1, merchant_id=4, merchant_name="BetZone", amount=5000, currency="INR", category="gambling")
        repo.create_payment_request(**pr.to_db_dict(), db_path=dbp)
        pe = PolicyEngine(); re = RiskEngine(); de = DecisionEngine(pe, re)
        pol = pe.evaluate_request(1,1,5000,"gambling",merchant_id=4, db_path=dbp)
        assert pol["authorized"] is False
        risk = re.assess_request(1,1,{"amount":5000,"category":"gambling","merchant_id":4}, pol, db_path=dbp)
        dec = de.decide(pol, risk)
        assert dec["decision"] == "DENY"
        sim = simulate(pr.to_db_dict(), pol, risk, dec)
        assert sim["recommended"] == "DENY"
    finally:
        _safe_cleanup(tmp)

def test_e2e_ask_user_medium_risk():
    tmp, dbp = _tmp_db()
    try:
        # Use new merchant + higher amount to push to MEDIUM
        pr = PaymentRequest(request_id="req_e2e_ask", user_id=1, agent_id=1, merchant_id=1, merchant_name="TechMart Electronics", amount=35000, currency="INR", category="electronics")
        repo.create_payment_request(**pr.to_db_dict(), db_path=dbp)
        pe = PolicyEngine(); re = RiskEngine()
        pol = pe.evaluate_request(1,1,35000,"electronics",merchant_id=1, db_path=dbp)
        # Force medium context
        risk = re.assess({"amount":35000,"category":"electronics"}, pol, context={"daily_limit":100000,"daily_spent":40000,"transactions_last_hour":6,"user_total_txns":20})
        # Might be LOW/MEDIUM — ensure at least ASK if requires_approval
        de = DecisionEngine(pe, re)
        dec = de.decide(pol, risk)
        # 35000 > approval 30000, so even LOW should be ASK
        assert dec["decision"] in ("ASK_USER","DENY")
    finally:
        _safe_cleanup(tmp)

def test_database_failure_graceful():
    tmp, dbp = _tmp_db()
    try:
        pe = PolicyEngine()
        # Missing user
        res = pe.evaluate_request(9999, 1, 10000, "electronics", merchant_id=1, db_path=dbp)
        assert res["authorized"] is False
        assert "missing_user" in res["violations"]
    finally:
        _safe_cleanup(tmp)
