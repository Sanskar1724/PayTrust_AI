"""HTTP API: auth, RBAC, validation, approvals lifecycle, directory, webhooks, ML, health."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import update

from app import db
from app.models import Payment
from app.services import approvals
from tests.conftest import payment


def _operator(client, admin_headers, role):
    email = f"{role}@example.com"
    client.post("/v1/operators", json={"email": email, "name": role, "role": role, "password": "password123"},
                headers=admin_headers)
    token = client.post("/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──

def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["checks"]["database"] == "ok"
    assert "paytrust_http_requests_total" in client.get("/metrics").text


def test_login_rejects_bad_password(client):
    resp = client.post("/v1/auth/login", json={"email": "admin@paytrust.local", "password": "wrong"})
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_requests_need_credentials(client):
    assert client.post("/v1/payments", json=payment()).status_code == 401
    assert client.post("/v1/payments", json=payment(), headers={"X-API-Key": "pt_deadbeef_nope"}).status_code == 401
    assert client.get("/v1/payments").status_code == 401
    assert client.get("/v1/payments", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_revoked_key_stops_working(client, admin_headers):
    created = client.post("/v1/agents/1/keys", json={}, headers=admin_headers).json()
    headers = {"X-API-Key": created["key"]}
    assert client.post("/v1/payments", json=payment(), headers=headers).status_code == 201
    assert client.delete(f"/v1/agents/1/keys/{created['id']}", headers=admin_headers).status_code == 204
    assert client.post("/v1/payments", json=payment(), headers=headers).status_code == 401


def test_disabled_agent_key_is_rejected(client, admin_headers, agent_key):
    client.patch("/v1/agents/1", json={"is_active": False}, headers=admin_headers)
    assert client.post("/v1/payments", json=payment(), headers=agent_key).status_code == 401


def test_roles_are_enforced(client, admin_headers, agent_key):
    viewer = _operator(client, admin_headers, "viewer")
    reviewer = _operator(client, admin_headers, "reviewer")
    pending = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()["request_id"]

    assert client.get("/v1/payments", headers=viewer).status_code == 200
    assert client.post(f"/v1/payments/{pending}/approve", headers=viewer).status_code == 403
    assert client.post("/v1/merchants", json={"name": "X"}, headers=reviewer).status_code == 403
    assert client.post(f"/v1/payments/{pending}/approve", headers=reviewer).status_code == 200


def test_rate_limit(client, agent_key, monkeypatch):
    from app.api import deps
    from app.services.ratelimit import RateLimiter

    monkeypatch.setattr(deps, "_limiter", RateLimiter(3, 60))
    codes = [client.post("/v1/payments", json=payment(), headers=agent_key).status_code for _ in range(4)]
    assert codes[:3] == [201, 201, 201] and codes[3] == 429


# ── Validation ──

@pytest.mark.parametrize("override, field", [
    ({"amount": -1}, "amount"),
    ({"amount": 12.5}, "amount"),
    ({"currency": "USD"}, "currency"),
    ({"category": "weapons"}, "category"),
    ({"request_id": "x"}, "request_id"),
    ({"unexpected": 1}, "unexpected"),
])
def test_payment_validation(client, agent_key, override, field):
    resp = client.post("/v1/payments", json=payment(**override), headers=agent_key)
    assert resp.status_code == 422
    assert any(field in d["field"] for d in resp.json()["error"]["details"])


# ── Approvals ──

def test_approve_flow_creates_order_and_releases_nothing(client, agent_key, admin_headers):
    body = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()
    assert body["status"] == "PENDING_APPROVAL" and body["expires_at"]
    assert body["ai"] is None  # the decision returns before the explanation is written
    stored = client.get(f"/v1/payments/{body['request_id']}", headers=admin_headers).json()
    assert stored["ai"]["provider"] == "deterministic"  # auto-investigated for the reviewer

    approved = client.post(f"/v1/payments/{body['request_id']}/approve", json={"note": "user confirmed"},
                           headers=admin_headers).json()
    assert approved["status"] == "APPROVED" and approved["reviewed_by"] == "admin@paytrust.local"
    detail = client.get(f"/v1/payments/{body['request_id']}", headers=agent_key).json()
    assert detail["order"]["id"].startswith("order_sim_")

    again = client.post(f"/v1/payments/{body['request_id']}/approve", headers=admin_headers)
    assert again.status_code == 409


def test_reject_releases_budget(client, agent_key, admin_headers):
    rid = client.post("/v1/payments", json=payment(amount=50_000), headers=agent_key).json()["request_id"]
    client.post(f"/v1/payments/{rid}/reject", headers=admin_headers)
    nxt = client.post("/v1/payments", json=payment(amount=9_000), headers=agent_key).json()
    assert nxt["policy_result"]["daily_spent"] == 0


def test_cannot_review_allowed_or_denied(client, agent_key, admin_headers):
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    assert client.post(f"/v1/payments/{rid}/approve", headers=admin_headers).status_code == 409


def test_pending_payments_expire(client, agent_key, admin_headers):
    rid = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()["request_id"]
    with db.session_scope() as s:
        s.execute(update(Payment).where(Payment.request_id == rid)
                  .values(expires_at=db.utcnow() - timedelta(minutes=1)))
    assert approvals.expire_due() == 1
    assert client.get(f"/v1/payments/{rid}", headers=admin_headers).json()["status"] == "EXPIRED"
    assert client.post(f"/v1/payments/{rid}/approve", headers=admin_headers).status_code == 409


def test_investigate_on_demand(client, agent_key, admin_headers):
    rid = client.post("/v1/payments", json=payment(category="gambling"), headers=agent_key).json()["request_id"]
    body = client.post(f"/v1/payments/{rid}/investigate", headers=admin_headers).json()
    assert body["ai"]["advisory_only"] is True
    assert body["decision"] == "DENY"  # explanation never changes the decision


def test_playground_and_listing(client, admin_headers):
    resp = client.post("/v1/playground/evaluate", json=payment(agent_id=1), headers=admin_headers)
    assert resp.status_code == 201 and resp.json()["source"] == "playground"
    page = client.get("/v1/payments?source=playground&q=TechMart", headers=admin_headers).json()
    assert page["total"] == 1 and page["items"][0]["request_id"] == resp.json()["request_id"]
    assert client.get("/v1/payments?decision=DENY", headers=admin_headers).json()["total"] == 0


def test_audit_trail_records_decisions_and_reviews(client, agent_key, admin_headers):
    rid = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()["request_id"]
    client.post(f"/v1/payments/{rid}/reject", headers=admin_headers)
    events = [e["event_type"] for e in client.get(f"/v1/audit?request_id={rid}", headers=admin_headers).json()["items"]]
    assert "PAYMENT_EVALUATED" in events and "PAYMENT_REJECTED" in events


def test_stats(client, agent_key, admin_headers):
    client.post("/v1/payments", json=payment(), headers=agent_key)
    client.post("/v1/payments", json=payment(category="gambling"), headers=agent_key)
    stats = client.get("/v1/stats", headers=admin_headers).json()
    assert stats["total"] == 2 and stats["decisions"]["DENY"] == 1
    assert stats["top_violations"][0][0] == "category_blocked"


# ── Directory ──

def test_policy_upsert_takes_effect(client, agent_key, admin_headers):
    policy = {"user_id": 1, "agent_id": 1, "daily_limit": 10_000, "max_transaction": 5_000,
              "approval_threshold": 4_000, "allowed_categories": ["electronics"], "blocked_categories": ["gambling"]}
    assert client.put("/v1/policies", json=policy, headers=admin_headers).status_code == 200
    body = client.post("/v1/payments", json=payment(amount=6_000), headers=agent_key).json()
    assert "max_transaction_exceeded" in body["policy_result"]["violations"]


def test_policy_validation(client, admin_headers):
    bad = {"user_id": 1, "agent_id": 1, "daily_limit": 1_000, "max_transaction": 5_000, "approval_threshold": 100}
    assert client.put("/v1/policies", json=bad, headers=admin_headers).status_code == 422
    overlap = {"user_id": 1, "agent_id": 1, "daily_limit": 9_000, "max_transaction": 5_000, "approval_threshold": 100,
               "allowed_categories": ["books"], "blocked_categories": ["books"]}
    assert client.put("/v1/policies", json=overlap, headers=admin_headers).status_code == 422


def test_create_agent_returns_secret_once(client, admin_headers):
    created = client.post("/v1/agents", json={"name": "Grocery Bot"}, headers=admin_headers)
    assert created.status_code == 201 and created.json()["webhook_secret"].startswith("whsec_")
    listed = client.get("/v1/agents", headers=admin_headers).json()
    assert all("webhook_secret" not in a for a in listed)
    assert client.post("/v1/agents", json={"name": "Grocery Bot"}, headers=admin_headers).status_code == 409


# ── Webhooks ──

def _signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(b"whsec_test_secret", raw, hashlib.sha256).hexdigest()
    return raw, {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}


def test_webhook_signature_and_idempotency(client):
    raw, headers = _signed({"id": "evt_1", "event": "payment.captured",
                            "payload": {"payment": {"entity": {"id": "pay_1"}}}})
    assert client.post("/v1/webhooks/razorpay", content=raw, headers=headers).json()["status"] == "processed"
    assert client.post("/v1/webhooks/razorpay", content=raw, headers=headers).json()["status"] == "duplicate"
    bad = client.post("/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "00"})
    assert bad.status_code == 401


# ── ML ──

def test_ml_threshold_tool(client, admin_headers):
    report = client.get("/v1/ml/report", headers=admin_headers).json()
    assert 0 < report["test"]["pr_auc"] < 1 and report["n_test"] == 3000
    curves = client.get("/v1/ml/curves", headers=admin_headers).json()
    assert len(curves["points"]) == 101 and curves["n"] == 3000
    zero = client.get("/v1/ml/metrics?threshold=0", headers=admin_headers).json()
    assert zero["recall"] == 1.0 and zero["fn"] == 0
    assert client.get("/v1/ml/metrics?threshold=2", headers=admin_headers).status_code == 422
