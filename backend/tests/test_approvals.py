"""Approval re-checks the mandate at the moment money would move."""
from __future__ import annotations

from sqlalchemy import select

from app import db
from app.models import AuditEvent
from tests.conftest import payment

POLICY = {"user_id": 1, "agent_id": 1, "daily_limit": 100_000, "max_transaction": 60_000,
          "approval_threshold": 30_000, "allowed_categories": ["electronics", "books", "travel"],
          "blocked_categories": ["gambling", "financial_products"]}


def _pending(client, agent_key, amount=40_000, **kw):
    body = client.post("/v1/payments", json=payment(amount=amount, **kw), headers=agent_key).json()
    assert body["status"] == "PENDING_APPROVAL", body
    return body


def _approve(client, admin_headers, request_id):
    return client.post(f"/v1/payments/{request_id}/approve", json={"note": "ok"}, headers=admin_headers)


def _get(client, admin_headers, request_id):
    return client.get(f"/v1/payments/{request_id}", headers=admin_headers).json()


def _assert_blocked(client, admin_headers, request_id, fragment):
    resp = _approve(client, admin_headers, request_id)
    assert resp.status_code == 409, resp.text
    assert fragment in resp.text
    stored = _get(client, admin_headers, request_id)
    assert stored["status"] == "REJECTED" and stored["reviewed_by"] == "system"
    assert fragment in stored["review_note"]
    assert stored["order"] is None  # no money moved
    with db.session_scope() as session:
        types = session.scalars(select(AuditEvent.event_type).where(AuditEvent.request_id == request_id)).all()
    assert "APPROVAL_BLOCKED" in types and "PAYMENT_APPROVED" not in types


def test_approval_still_works_when_nothing_changed(client, agent_key, admin_headers):
    rid = _pending(client, agent_key)["request_id"]
    resp = _approve(client, admin_headers, rid)
    assert resp.status_code == 200 and resp.json()["status"] == "APPROVED"


def test_approval_blocked_after_the_api_key_is_revoked(client, agent_key, admin_headers):
    """A stolen key is discovered and revoked: its pending payments must not go through."""
    rid = _pending(client, agent_key)["request_id"]
    keys = next(a for a in client.get("/v1/agents", headers=admin_headers).json() if a["id"] == 1)["keys"]
    key_id = next(k["id"] for k in keys if k["name"] == "tests")
    assert client.delete(f"/v1/agents/1/keys/{key_id}", headers=admin_headers).status_code == 204
    _assert_blocked(client, admin_headers, rid, "API key that submitted this payment has been revoked")


def test_approval_blocked_after_the_agent_is_disabled(client, agent_key, admin_headers):
    rid = _pending(client, agent_key)["request_id"]
    assert client.patch("/v1/agents/1", json={"is_active": False}, headers=admin_headers).status_code == 200
    _assert_blocked(client, admin_headers, rid, "disabled")


def test_approval_blocked_when_the_policy_was_tightened(client, agent_key, admin_headers):
    rid = _pending(client, agent_key, amount=40_000)["request_id"]
    tighter = POLICY | {"max_transaction": 35_000, "daily_limit": 80_000}
    assert client.put("/v1/policies", json=tighter, headers=admin_headers).status_code == 200
    _assert_blocked(client, admin_headers, rid, "per-transaction maximum")


def test_approval_blocked_when_the_merchant_became_a_blocked_category(client, agent_key, admin_headers):
    rid = _pending(client, agent_key)["request_id"]
    resp = client.put("/v1/merchants/1", json={"name": "TechMart Electronics", "category": "gambling",
                                               "risk_tier": "high"}, headers=admin_headers)
    assert resp.status_code == 200
    _assert_blocked(client, admin_headers, rid, "registered as 'gambling'")


def test_approval_daily_limit_does_not_count_the_payment_twice(client, agent_key, admin_headers):
    """The pending payment already reserves its amount; re-checking must not add it again."""
    rid = _pending(client, agent_key, amount=55_000)["request_id"]  # 55k of a 100k limit
    resp = _approve(client, admin_headers, rid)
    assert resp.status_code == 200 and resp.json()["status"] == "APPROVED"


def test_approval_blocked_when_the_daily_limit_was_lowered(client, agent_key, admin_headers):
    first = _pending(client, agent_key, amount=40_000)["request_id"]
    second = _pending(client, agent_key, amount=45_000, merchant_id=2, merchant_name="BookHaven",
                      category="books")["request_id"]
    assert client.put("/v1/policies", json=POLICY | {"daily_limit": 60_000}, headers=admin_headers).status_code == 200
    assert _approve(client, admin_headers, first).status_code == 409  # 45k reserved by the other + 40k > 60k
    # The first one was rejected, which releases its reservation, so the second now fits.
    assert _approve(client, admin_headers, second).status_code == 200
