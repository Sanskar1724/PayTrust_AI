"""Per-agent limits + the optional user budget across all of a user's agents."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app import db
from app.db import utcnow
from app.domain.policy import DEFAULT_RULES, Spend, evaluate_policy
from app.models import AuditEvent, Payment, PaymentStatus
from app.services import evaluation
from app.services.evaluation import period_bounds, spend_snapshot
from tests.conftest import payment

SMALL_POLICY = {"daily_limit": 10_000, "max_transaction": 8_000, "approval_threshold": 8_000,
                "allowed_categories": ["electronics", "books", "grocery"], "blocked_categories": ["gambling"]}


def _second_agent(client, admin_headers, policy=SMALL_POLICY) -> dict[str, str]:
    """A second agent for user 1 with its own (small) policy; returns its API-key header."""
    agent = client.post("/v1/agents", json={"name": "Grocery Bot"}, headers=admin_headers).json()
    key = client.post(f"/v1/agents/{agent['id']}/keys", json={"name": "t"}, headers=admin_headers).json()["key"]
    resp = client.put("/v1/policies", json={"user_id": 1, "agent_id": agent["id"], **policy}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return {"X-API-Key": key}


def test_one_agents_spending_does_not_use_up_another_agents_limit(client, agent_key, admin_headers):
    """Regression: 'spent today' counted ALL agents, so a big ShopBuddy purchase blocked the grocery bot."""
    grocery = _second_agent(client, admin_headers)
    big = client.post("/v1/payments", json=payment(amount=45_000), headers=agent_key).json()
    assert big["status"] == "PENDING_APPROVAL"  # reserves 45k against agent 1's policy only
    small = client.post("/v1/payments", json=payment(amount=4_000, category="grocery", merchant_id=4,
                                                     merchant_name="FreshCart"), headers=grocery).json()
    assert small["decision"] == "ALLOW", small["reasons"]
    assert small["policy_result"]["daily_spent"] == 0  # this agent's own spend
    assert small["policy_result"]["spend"]["user"]["day"] == 45_000  # the user's total is still reported


def test_each_agent_still_hits_its_own_limit(client, admin_headers):
    grocery = _second_agent(client, admin_headers)
    for amount in (3_000, 3_000, 3_000):
        client.post("/v1/payments", json=payment(amount=amount, category="grocery", merchant_id=4,
                                                 merchant_name="FreshCart", description=f"order {amount}"),
                    headers=grocery)
    over = client.post("/v1/payments", json=payment(amount=2_500, category="books", merchant_id=2,
                                                    merchant_name="BookHaven"), headers=grocery).json()
    assert "daily_limit_exceeded" in over["policy_result"]["violations"]


def test_user_daily_budget_caps_all_agents_together(client, agent_key, admin_headers):
    grocery = _second_agent(client, admin_headers)
    assert client.patch("/v1/users/1", json={"daily_budget": 20_000}, headers=admin_headers).status_code == 200
    first = client.post("/v1/payments", json=payment(amount=15_000), headers=agent_key).json()
    assert first["decision"] == "ALLOW"
    second = client.post("/v1/payments", json=payment(amount=6_000, category="grocery", merchant_id=4,
                                                      merchant_name="FreshCart"), headers=grocery).json()
    assert second["decision"] == "DENY"
    assert second["policy_result"]["violations"] == ["user_daily_budget_exceeded"]
    assert "all agents together" in second["policy_result"]["reasons"][0]


def test_approval_recheck_honours_the_user_budget(client, agent_key, admin_headers):
    pending = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()
    assert pending["status"] == "PENDING_APPROVAL"
    client.patch("/v1/users/1", json={"daily_budget": 30_000}, headers=admin_headers)
    resp = client.post(f"/v1/payments/{pending['request_id']}/approve", headers=admin_headers)
    assert resp.status_code == 409 and "daily budget" in resp.text


# ── Spend periods ──

def _row(rid: str, day: str, agent_id: int, amount: int, status: str = PaymentStatus.ALLOWED) -> Payment:
    return Payment(request_id=rid, body_hash="x", user_id=1, agent_id=agent_id, merchant_id=1, merchant_name="M",
                   amount=amount, category="books", status=status, decision="ALLOW", risk_score=0,
                   risk_level="LOW", spend_day=day, created_at=utcnow(), updated_at=utcnow())


def test_period_bounds_use_monday_weeks_and_calendar_months():
    b = period_bounds("2026-11-12")  # a Thursday
    assert b["day"] == ("2026-11-12", "2026-11-12")
    assert b["week"] == ("2026-11-09", "2026-11-15")
    assert b["month"] == ("2026-11-01", "2026-11-30")
    assert period_bounds("2028-02-10")["month"] == ("2028-02-01", "2028-02-29")  # leap year
    assert period_bounds("2026-12-31")["month"] == ("2026-12-01", "2026-12-31")
    assert period_bounds("2026-03-01")["week"] == ("2026-02-23", "2026-03-01")  # week spans two months


def test_spend_snapshot_sums_each_period_per_agent_and_in_total(client):
    with db.session_scope() as session:
        session.add_all([
            _row("r_today_a1", "2026-11-12", 1, 1_000),
            _row("r_today_a2", "2026-11-12", 2, 2_000),
            _row("r_tue_a1", "2026-11-10", 1, 300),                         # same week
            _row("r_prev_week", "2026-11-03", 1, 40),                       # same month, previous week
            _row("r_prev_month", "2026-10-31", 1, 5),                       # previous month (and week)
            _row("r_pending", "2026-11-12", 1, 7, PaymentStatus.PENDING_APPROVAL),  # reserved: counts
            _row("r_denied", "2026-11-12", 1, 9_999, PaymentStatus.DENIED),         # never counts
            _row("r_rejected", "2026-11-11", 1, 8_888, PaymentStatus.REJECTED),     # released: never counts
        ])
    with db.session_scope() as session:
        agent, total = spend_snapshot(session, user_id=1, agent_id=1, day="2026-11-12")
        excluded = session.scalar(select(Payment.id).where(Payment.request_id == "r_today_a1"))
        agent_ex, _ = spend_snapshot(session, 1, 1, "2026-11-12", exclude_payment_id=excluded)
    assert agent == Spend(day=1_007, week=1_307, month=1_347)
    assert total == Spend(day=3_007, week=3_307, month=3_347)
    assert agent_ex.day == 7  # the payment being re-checked never counts against itself


def test_weekly_and_monthly_user_budgets():
    pay = {"amount": 1_000, "category": "electronics", "merchant_id": 1, "merchant_name": "TechMart"}
    budget = {"daily": None, "weekly": 10_000, "monthly": 30_000}
    ok = evaluate_policy(DEFAULT_RULES, pay, user_spend=Spend(day=0, week=9_000, month=20_000), user_budget=budget)
    assert ok["authorized"]
    week = evaluate_policy(DEFAULT_RULES, pay, user_spend=Spend(day=0, week=9_500, month=20_000), user_budget=budget)
    assert week["violations"] == ["user_weekly_budget_exceeded"]
    month = evaluate_policy(DEFAULT_RULES, pay, user_spend=Spend(day=0, week=0, month=29_500), user_budget=budget)
    assert month["violations"] == ["user_monthly_budget_exceeded"]
    assert len(month["reasons"]) >= len(month["violations"])
    no_budget = evaluate_policy(DEFAULT_RULES, pay, user_spend=Spend(day=10**6, week=10**6, month=10**6))
    assert no_budget["authorized"]  # without a budget only the agent's own limits apply


# ── Budget API ──

def test_budget_api_validates_and_audits(client, admin_headers):
    ok = client.patch("/v1/users/1", json={"daily_budget": 5_000, "weekly_budget": 20_000, "monthly_budget": 60_000},
                      headers=admin_headers)
    assert ok.status_code == 200
    assert (ok.json()["daily_budget"], ok.json()["weekly_budget"], ok.json()["monthly_budget"]) == (5_000, 20_000,
                                                                                                    60_000)
    bad = client.patch("/v1/users/1", json={"daily_budget": 50_000, "weekly_budget": 20_000}, headers=admin_headers)
    assert bad.status_code == 422 and "daily_budget cannot exceed weekly_budget" in bad.text
    # A partial update is checked against what is already stored (weekly is 20,000).
    partial = client.patch("/v1/users/1", json={"daily_budget": 25_000}, headers=admin_headers)
    assert partial.status_code == 422
    cleared = client.patch("/v1/users/1", json={"weekly_budget": None, "monthly_budget": None}, headers=admin_headers)
    assert cleared.status_code == 200 and cleared.json()["weekly_budget"] is None
    assert cleared.json()["daily_budget"] == 5_000  # untouched fields keep their value
    assert client.patch("/v1/users/999", json={"daily_budget": 1}, headers=admin_headers).status_code == 404
    with db.session_scope() as session:
        assert session.scalar(select(AuditEvent.id).where(AuditEvent.event_type == "USER_UPDATED"))


# ── Weekly / monthly limits per policy ──

def test_weekly_and_monthly_policy_limits():
    rules = {**DEFAULT_RULES.summary(), "weekly_limit": 50_000, "monthly_limit": 1_20_000}
    pay = {"amount": 10_000, "category": "electronics", "merchant_id": 1, "merchant_name": "TechMart"}
    assert evaluate_policy(rules, pay, agent_spend=Spend(day=0, week=40_000, month=1_00_000))["authorized"]
    week = evaluate_policy(rules, pay, agent_spend=Spend(day=0, week=40_001, month=40_001))
    assert week["violations"] == ["weekly_limit_exceeded"]
    assert week["reasons"][0].startswith("Weekly limit INR 50,000 exceeded: INR 40,001 already used this week")
    month = evaluate_policy(rules, pay, agent_spend=Spend(day=0, week=0, month=1_15_000))
    assert month["violations"] == ["monthly_limit_exceeded"]
    no_limits = evaluate_policy(DEFAULT_RULES.summary(), pay, agent_spend=Spend(day=0, week=10**7, month=10**7))
    assert no_limits["authorized"]  # weekly/monthly limits are optional


def test_weekly_limit_through_the_api(client, agent_key, admin_headers, monkeypatch):
    """Spend earlier in the same week counts toward the weekly limit, not toward today's."""
    thursday = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)  # 11:30 in Asia/Kolkata
    monkeypatch.setattr(evaluation, "utcnow", lambda: thursday)
    policy = {"user_id": 1, "agent_id": 1, "daily_limit": 20_000, "weekly_limit": 20_000, "monthly_limit": 80_000,
              "max_transaction": 20_000, "approval_threshold": 20_000,
              "allowed_categories": ["electronics", "books"], "blocked_categories": ["gambling"]}
    saved = client.put("/v1/policies", json=policy, headers=admin_headers)
    assert saved.status_code == 200 and saved.json()["weekly_limit"] == 20_000
    with db.session_scope() as session:
        session.add(_row("r_tuesday", "2026-11-10", 1, 15_000))  # same week, earlier day
    body = client.post("/v1/payments", json=payment(amount=6_000), headers=agent_key).json()
    assert body["policy_result"]["daily_spent"] == 0  # nothing yet today…
    assert body["policy_result"]["spend"]["agent"]["week"] == 15_000  # …but 15,000 this week
    assert body["policy_result"]["violations"] == ["weekly_limit_exceeded"]
    assert any(f["details"] == "Weekly limit would be exceeded" for f in body["risk_result"]["factors"])


def test_policy_period_limits_must_be_ordered(client, admin_headers):
    base = {"user_id": 1, "agent_id": 1, "daily_limit": 10_000, "max_transaction": 5_000, "approval_threshold": 4_000}
    bad = client.put("/v1/policies", json=base | {"weekly_limit": 9_000}, headers=admin_headers)
    assert bad.status_code == 422 and "daily_limit cannot exceed weekly_limit" in bad.text
    bad = client.put("/v1/policies", json=base | {"weekly_limit": 50_000, "monthly_limit": 40_000}, headers=admin_headers)
    assert bad.status_code == 422 and "weekly_limit cannot exceed monthly_limit" in bad.text
    assert client.put("/v1/policies", json=base | {"monthly_limit": 10_000}, headers=admin_headers).status_code == 200
