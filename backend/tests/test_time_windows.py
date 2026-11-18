"""Time windows: the hours and weekdays during which an agent may start payments."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.policy import DEFAULT_RULES, evaluate_policy, within_hours
from app.services import evaluation
from tests.conftest import payment

IST = timezone(timedelta(hours=5, minutes=30))
POLICY = {"user_id": 1, "agent_id": 1, "daily_limit": 100_000, "max_transaction": 60_000,
          "approval_threshold": 30_000, "allowed_categories": ["electronics", "books"],
          "blocked_categories": ["gambling"]}
PAY = {"amount": 1_000, "category": "electronics", "merchant_id": 1, "merchant_name": "TechMart"}


def _at(hour: int, minute: int = 0, day: int = 12) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)  # 2026-11-12 is a Thursday


@pytest.mark.parametrize("hhmm,inside", [("05:59", False), ("06:00", True), ("21:59", True), ("22:00", False)])
def test_daytime_window_boundaries(hhmm, inside):
    h, m = map(int, hhmm.split(":"))
    rules = {**DEFAULT_RULES.summary(), "allowed_from": "06:00", "allowed_until": "22:00"}
    result = evaluate_policy(rules, PAY, local_time=_at(h, m))
    assert result["authorized"] is inside
    if not inside:
        assert result["violations"] == ["outside_allowed_hours"]
        assert f"the request came at {hhmm}" in result["reasons"][0]


def test_overnight_window_wraps_past_midnight():
    assert within_hours("22:00", "06:00", _at(23, 30).time())
    assert within_hours("22:00", "06:00", _at(5, 59).time())
    assert not within_hours("22:00", "06:00", _at(6, 0).time())
    assert not within_hours("22:00", "06:00", _at(12, 0).time())


def test_allowed_days():
    rules = {**DEFAULT_RULES.summary(), "allowed_days": ["mon", "tue", "wed", "thu", "fri", "sat"]}
    assert evaluate_policy(rules, PAY, local_time=_at(12, 0, day=12))["authorized"]  # Thursday
    sunday = evaluate_policy(rules, PAY, local_time=_at(12, 0, day=15))
    assert sunday["violations"] == ["outside_allowed_days"]
    assert "Mon, Tue, Wed, Thu, Fri, Sat" in sunday["reasons"][0] and "Sunday" in sunday["reasons"][0]


def test_no_window_or_no_clock_means_no_time_checks():
    assert evaluate_policy(DEFAULT_RULES, PAY, local_time=_at(3, 0))["authorized"]
    rules = {**DEFAULT_RULES.summary(), "allowed_from": "06:00", "allowed_until": "22:00"}
    assert evaluate_policy(rules, PAY)["authorized"]  # callers that pass no clock skip the window


def test_time_window_through_the_api_uses_the_spend_timezone(client, agent_key, admin_headers, monkeypatch):
    window = POLICY | {"allowed_from": "06:00", "allowed_until": "22:00"}
    assert client.put("/v1/policies", json=window, headers=admin_headers).status_code == 200
    # 17:00 UTC = 22:30 in Asia/Kolkata: outside the window even though it is daytime in UTC.
    monkeypatch.setattr(evaluation, "utcnow", lambda: datetime(2026, 11, 12, 17, 0, tzinfo=UTC))
    late = client.post("/v1/payments", json=payment(), headers=agent_key).json()
    assert late["decision"] == "DENY" and late["policy_result"]["violations"] == ["outside_allowed_hours"]
    assert any("hours this agent may pay" in f["details"] for f in late["risk_result"]["factors"])
    monkeypatch.setattr(evaluation, "utcnow", lambda: datetime(2026, 11, 12, 6, 0, tzinfo=UTC))  # 11:30 IST
    # (a different amount: the denied 22:30 attempt would otherwise count as a repeat of this one)
    ok = client.post("/v1/payments", json=payment(amount=2_499, description="daytime"), headers=agent_key).json()
    assert ok["decision"] == "ALLOW"


def test_approval_recheck_uses_the_time_the_agent_asked(client, agent_key, admin_headers, monkeypatch):
    """Requested at 21:50, approved at 22:10: the window governs agents, not reviewers."""
    client.put("/v1/policies", json=POLICY | {"allowed_from": "06:00", "allowed_until": "22:00"},
               headers=admin_headers)
    asked = datetime(2026, 11, 12, 16, 20, tzinfo=UTC)  # 21:50 IST
    monkeypatch.setattr(evaluation, "utcnow", lambda: asked)
    pending = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()
    assert pending["status"] == "PENDING_APPROVAL"
    from app.services import approvals
    later = asked + timedelta(minutes=20)  # 22:10 IST: outside the window, inside the 30-minute approval TTL
    monkeypatch.setattr(approvals, "utcnow", lambda: later)
    monkeypatch.setattr(evaluation, "utcnow", lambda: later)
    resp = client.post(f"/v1/payments/{pending['request_id']}/approve", headers=admin_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "APPROVED"


def test_time_window_validation(client, admin_headers):
    def put(extra):
        return client.put("/v1/policies", json=POLICY | extra, headers=admin_headers)

    assert put({"allowed_from": "06:00"}).status_code == 422                          # only one end
    assert put({"allowed_from": "6:00", "allowed_until": "22:00"}).status_code == 422  # not HH:MM
    assert put({"allowed_from": "24:00", "allowed_until": "22:00"}).status_code == 422
    assert put({"allowed_from": "09:00", "allowed_until": "09:00"}).status_code == 422
    assert put({"allowed_days": ["mon", "funday"]}).status_code == 422
    saved = put({"allowed_from": "22:00", "allowed_until": "06:00", "allowed_days": ["Sat", "monday", "mon"]})
    assert saved.status_code == 200
    assert saved.json()["allowed_days"] == ["mon", "sat"]  # normalised, de-duplicated, in week order
