"""Regression tests for the v1 bugs, the duplicate-payment gap and the pipeline guarantees."""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from tests.conftest import payment


def test_first_payment_is_not_double_counted_against_daily_limit(client, agent_key):
    """v1 bug: ₹55,000 as the first payment of the day was DENIED as 55k + 55k > 100k."""
    resp = client.post("/v1/payments", json=payment(amount=55_000), headers=agent_key)
    assert resp.status_code == 201
    body = resp.json()
    assert "daily_limit_exceeded" not in body["policy_result"]["violations"]
    assert body["policy_result"]["daily_spent"] == 0
    assert body["decision"] == "ASK_USER"  # above the 30k approval threshold, not denied


def test_denied_payments_do_not_consume_budget(client, agent_key):
    """v1 bug: every attempt, including DENIED ones, counted toward the daily limit."""
    denied = client.post("/v1/payments", json=payment(amount=59_000, category="gambling"), headers=agent_key).json()
    assert denied["decision"] == "DENY"
    nxt = client.post("/v1/payments", json=payment(amount=8_000), headers=agent_key).json()
    assert nxt["policy_result"]["daily_spent"] == 0


def test_new_merchant_signal_fires_on_first_payment(client, agent_key):
    """v1 bug: the request was stored before the check, so is_new_merchant was never true."""
    first = client.post("/v1/payments", json=payment(), headers=agent_key).json()
    names = [f["details"] for f in first["risk_result"]["factors"]]
    assert any("First payment from this user to this merchant" in n for n in names)
    assert first["risk_result"]["context"]["is_new_merchant"] is True
    second = client.post("/v1/payments", json=payment(amount=4_321), headers=agent_key).json()
    assert second["risk_result"]["context"]["is_new_merchant"] is False


def test_pending_approval_reserves_budget(client, agent_key):
    pending = client.post("/v1/payments", json=payment(amount=45_000), headers=agent_key).json()
    assert pending["status"] == "PENDING_APPROVAL"
    second = client.post("/v1/payments", json=payment(amount=58_000), headers=agent_key).json()
    assert second["policy_result"]["daily_spent"] == 45_000
    assert "daily_limit_exceeded" in second["policy_result"]["violations"]


def test_mislabelled_category_at_blocked_merchant_is_denied(client, agent_key):
    """v1 gap: an agent could call a gambling merchant 'electronics' and only got a note."""
    body = client.post("/v1/payments", json=payment(merchant_id=5, merchant_name="BetZone", category="electronics"),
                       headers=agent_key).json()
    assert body["decision"] == "DENY"
    assert "merchant_category_blocked" in body["policy_result"]["violations"]


def test_runaway_loop_is_stopped(client, agent_key):
    """Arena finding: identical repeats scored LOW forever. Now: 1st ALLOW, repeats ASK/DENY."""
    decisions = [client.post("/v1/payments", json=payment(amount=4_999), headers=agent_key).json()["decision"]
                 for _ in range(6)]
    assert decisions[0] == "ALLOW"
    assert all(d in ("ASK_USER", "DENY") for d in decisions[1:])
    assert decisions[-1] == "DENY"


def test_idempotent_replay_returns_stored_decision(client, agent_key):
    body = payment(amount=12_000)
    first = client.post("/v1/payments", json=body, headers=agent_key)
    again = client.post("/v1/payments", json=body, headers=agent_key)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["decision"] == first.json()["decision"]
    assert again.json()["created_at"] == first.json()["created_at"]


def test_request_id_reuse_with_different_body_conflicts(client, agent_key):
    body = payment()
    client.post("/v1/payments", json=body, headers=agent_key)
    resp = client.post("/v1/payments", json=body | {"amount": 6_000}, headers=agent_key)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_concurrent_payments_never_exceed_daily_limit(app, client, agent_key):
    """Six parallel ₹28,000 payments against a ₹100,000 limit: at most three may hold budget."""
    results: list[dict] = []
    lock = threading.Lock()

    def fire():
        r = TestClient(app).post("/v1/payments", json=payment(amount=28_000), headers=agent_key)
        with lock:
            results.append(r.json())

    threads = [threading.Thread(target=fire) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    holding = [r for r in results if r["status"] in ("ALLOWED", "PENDING_APPROVAL", "APPROVED")]
    assert len(results) == 6
    assert sum(r["amount"] for r in holding) <= 100_000
    assert any("daily_limit_exceeded" in r["policy_result"]["violations"] for r in results)


def test_agent_key_cannot_act_as_another_agent(client, agent_key):
    body = client.post("/v1/payments", json=payment(agent_id=2), headers=agent_key).json()
    assert body["decision"] == "DENY"
    assert "agent_key_mismatch" in body["policy_result"]["violations"]


def test_unknown_user_is_recorded_and_denied(client, agent_key):
    body = client.post("/v1/payments", json=payment(user_id=999), headers=agent_key).json()
    assert body["decision"] == "DENY"
    assert {"missing_user", "missing_policy"} <= set(body["policy_result"]["violations"])


def test_allowed_payment_gets_an_order(client, agent_key):
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    body = client.get(f"/v1/payments/{rid}", headers=agent_key).json()
    assert body["status"] == "ALLOWED"
    assert body["order"]["id"].startswith("order_sim_")


def test_agents_only_see_their_own_payments(client, agent_key, admin_headers):
    other = client.post("/v1/agents/2/keys", json={}, headers=admin_headers).json()["key"]
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    assert client.get(f"/v1/payments/{rid}", headers={"X-API-Key": other}).status_code == 404
    assert client.get(f"/v1/payments/{rid}", headers=admin_headers).status_code == 200
