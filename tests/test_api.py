"""tests/test_api.py — HTTP service layer tests (FastAPI TestClient + httpx).

Uses an isolated tmp SQLite DB per test (same pattern as test_integration.py).
The engines are already covered by their own suites — this file verifies the
service wiring: auth, rate limit, validation mapping, idempotency, webhook.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

import pytest

from api.main import create_app
from api.security import api_key_for
from database.database import init_db


def _tmp_db():
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name) / "api_test.db"
    init_db(seed=True, db_path=p)
    return tmp, p


def _safe_cleanup(tmp):
    import gc
    gc.collect()
    time.sleep(0.05)
    try:
        tmp.cleanup()
    except PermissionError:
        gc.collect()
        time.sleep(0.1)
        try:
            tmp.cleanup()
        except Exception:
            pass


def _client(tmp_db_path):
    app = create_app(db_path=tmp_db_path)
    return TestClient(app)


def _auth():
    return {"X-API-Key": api_key_for()}


def _valid_payload(amount=25000, category="electronics", request_id="req_api_0001"):
    return {
        "request_id": request_id,
        "user_id": 1,
        "agent_id": 1,
        "merchant_id": 1,
        "merchant_name": "TechMart Electronics",
        "amount": amount,
        "currency": "INR",
        "category": category,
        "description": "API test purchase",
        "agent_reason": "user requested",
    }


# ── Health / readiness ──

def test_health_ok():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("ok", "degraded")
        assert body["version"]
        assert body["environment"] == "development"
    finally:
        _safe_cleanup(tmp)


def test_ready_ok():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True
        assert r.json()["database"] is True
    finally:
        _safe_cleanup(tmp)
# ── Evaluate pipeline ──

def test_evaluate_allow_flow():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.post("/v1/evaluate", json=_valid_payload(), headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["decision"] == "ALLOW"
        assert body["risk_level"] == "LOW"
        assert body["processing_ms"] >= 0
        assert body["duplicate"] is False
        # Deterministic decision is ALLOW; counterfactual simulator may recommend a
        # cheaper action (SIMULATED costs) — both must be present & valid.
        assert body["simulation"]["recommended"] in ("ALLOW", "ASK_USER", "DENY")
        assert len(body["simulation"]["counterfactuals"]) == 3
        assert "disclaimer" in body
        # persisted → list + detail
        lst = client.get("/v1/payments", headers=_auth()).json()
        assert lst["count"] >= 1
        det = client.get(f"/v1/payments/{body['request_id']}", headers=_auth()).json()
        assert det["decision"]["decision"] == "ALLOW"
    finally:
        _safe_cleanup(tmp)


def test_evaluate_deny_blocked_category():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        payload = _valid_payload(request_id="req_api_gamb", category="gambling")
        payload["merchant_id"] = 4
        payload["merchant_name"] = "BetZone"
        r = client.post("/v1/evaluate", json=payload, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["decision"] == "DENY"
        assert "category_blocked" in body["policy_result"]["violations"]
    finally:
        _safe_cleanup(tmp)


def test_evaluate_ask_user_amount():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        # 35k > approval_threshold 30k → ASK_USER
        r = client.post("/v1/evaluate", json=_valid_payload(amount=35000, request_id="req_api_ask"), headers=_auth())
        assert r.status_code == 200
        assert r.json()["decision"] == "ASK_USER"
    finally:
        _safe_cleanup(tmp)


def test_evaluate_validation_error_422():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        bad = _valid_payload()
        bad["amount"] = 0
        r = client.post("/v1/evaluate", json=bad, headers=_auth())
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "VALIDATION_ERROR"
    finally:
        _safe_cleanup(tmp)


def test_evaluate_idempotent_retry():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        rid = "req_api_idem"
        r1 = client.post("/v1/evaluate", json=_valid_payload(request_id=rid), headers=_auth())
        r2 = client.post("/v1/evaluate", json=_valid_payload(request_id=rid), headers=_auth())
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["duplicate"] is False
        assert r2.json()["duplicate"] is True
        assert r1.json()["decision"] == r2.json()["decision"] == "ALLOW"
    finally:
        _safe_cleanup(tmp)


def test_evaluate_with_ai_investigation_deterministic(monkeypatch):
    # Hermetic: force the deterministic provider even if a real key exists in .env —
    # this test must never depend on live LLM availability/rate limits.
    from engines import ai_engine as ai_mod
    monkeypatch.setattr(ai_mod.settings, "OPENROUTER_API_KEY", None)
    monkeypatch.setattr(ai_mod.settings, "GROQ_API_KEY", None)
    monkeypatch.setattr(ai_mod.settings, "GEMINI_API_KEY", None)
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        payload = _valid_payload(request_id="req_api_ai")
        payload["investigate"] = True
        r = client.post("/v1/evaluate", json=payload, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["ai"] is not None
        assert body["ai"]["provider"] in ("deterministic", "openrouter", "groq", "gemini")
        assert "explanation" in body["ai"]
        assert body["decision"] == "ALLOW"  # AI never overrides
    finally:
        _safe_cleanup(tmp)


def test_payments_not_found():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/payments/req_nope_0001", headers=_auth())
        assert r.status_code == 404
    finally:
        _safe_cleanup(tmp)


# ── Auth ──

def test_evaluate_requires_api_key():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.post("/v1/evaluate", json=_valid_payload())
        assert r.status_code == 401
        r = client.post("/v1/evaluate", json=_valid_payload(), headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401
    finally:
        _safe_cleanup(tmp)


def test_request_id_header_echoed():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/health", headers={"X-Request-ID": "abc123"})
        assert r.headers.get("X-Request-ID") == "abc123"
    finally:
        _safe_cleanup(tmp)
# ── Webhook ──

def test_webhook_processed_then_duplicate(monkeypatch):
    from services import razorpay_service
    monkeypatch.setattr(razorpay_service.settings, "RAZORPAY_WEBHOOK_SECRET", "test-secret")
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        raw = json.dumps({"id": "evt_001", "event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_001"}}}}).encode()
        sig = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        r1 = client.post("/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})
        assert r1.status_code == 200
        assert r1.json()["status"] == "processed"
        r2 = client.post("/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})
        assert r2.status_code == 200
        assert r2.json()["status"] == "duplicate"
    finally:
        _safe_cleanup(tmp)


def test_webhook_invalid_signature_rejected(monkeypatch):
    from services import razorpay_service
    monkeypatch.setattr(razorpay_service.settings, "RAZORPAY_WEBHOOK_SECRET", "test-secret")
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        raw = json.dumps({"id": "evt_002", "event": "payment.failed"}).encode()
        r = client.post("/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "deadbeef"})
        assert r.status_code == 400
        assert r.json()["detail"]["reason"] == "invalid_signature"
    finally:
        _safe_cleanup(tmp)


def test_webhook_missing_signature():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.post("/v1/webhooks/razorpay", content=b"{}")
        assert r.status_code == 400
        assert r.json()["detail"]["reason"] == "missing_signature"
    finally:
        _safe_cleanup(tmp)


# ── Evaluation metrics ──

def test_evaluation_metrics_real_reports():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/evaluation/metrics", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["ieee"] is not None
        assert "disclaimer" in body
    finally:
        _safe_cleanup(tmp)


def test_evaluation_metrics_requires_key():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        assert client.get("/v1/evaluation/metrics").status_code == 401
    finally:
        _safe_cleanup(tmp)


# ── Threshold decision tool ──
# These read the real IEEE held-out test predictions (evaluation/*.parquet),
# independent of the per-test DB — they verify the operating-point contract.

def test_threshold_at_returns_metrics():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/threshold", params={"p": 0.5}, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        for k in ("threshold", "precision", "recall", "f1", "false_positive_rate",
                  "false_negative_rate", "tp", "fp", "tn", "fn", "blocked_count",
                  "fraud_exposure", "false_positive_cost", "expected_total_cost", "disclaimer"):
            assert k in body, f"missing key {k}"
        assert body["threshold"] == 0.5
        assert 0.0 <= body["precision"] <= 1.0
        assert 0.0 <= body["recall"] <= 1.0
        assert body["tp"] + body["fp"] + body["tn"] + body["fn"] == body["blocked_count"] + body["allowed_count"]
        if body["tp"] + body["fp"]:  # precision defined when any positive prediction
            assert body["precision"] == pytest.approx(body["tp"] / (body["tp"] + body["fp"]))
        assert "SIMULATED" in body["disclaimer"]
    finally:
        _safe_cleanup(tmp)


def test_threshold_curves_returns_arrays():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/threshold/curves", headers=_auth())
        assert r.status_code == 200
        curves = r.json()
        for k in ("threshold", "precision", "recall", "f1", "false_positive_rate",
                  "fraud_exposure", "false_positive_cost", "expected_total_cost"):
            assert k in curves and len(curves[k]) > 50, f"curve missing/short: {k}"
        assert len(curves["threshold"]) == len(curves["precision"])
    finally:
        _safe_cleanup(tmp)


def test_threshold_recommend_returns_both_hints():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/threshold/recommend", headers=_auth())
        assert r.status_code == 200
        b = r.json()
        assert "max_f1" in b and "min_expected_total_cost" in b
        assert "disclaimer" in b
        assert b["max_f1"]["f1"] >= 0.0
        assert b["min_expected_total_cost"]["expected_total_cost"] >= 0.0
    finally:
        _safe_cleanup(tmp)


def test_threshold_check_reports_availability():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        r = client.get("/v1/threshold/check", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["rows"] > 0
    finally:
        _safe_cleanup(tmp)


def test_threshold_requires_api_key():
    tmp, dbp = _tmp_db()
    try:
        client = _client(dbp)
        assert client.get("/v1/threshold").status_code == 401
        assert client.get("/v1/threshold/curves").status_code == 401
    finally:
        _safe_cleanup(tmp)