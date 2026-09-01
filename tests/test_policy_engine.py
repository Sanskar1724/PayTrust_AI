"""
tests/test_policy_engine.py — Phase 3 deterministic policy tests (10 required cases).

Example policy (DEFAULT_POLICY):
  daily 100k, max 60k, approval>30k,
  allowed electronics/books/travel, blocked gambling/financial_products
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engines.policy_engine import PolicyEngine, Policy, DEFAULT_POLICY
from database.database import init_db
from database import repositories as repo


@pytest.fixture
def engine():
    return PolicyEngine()

@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(seed=True, db_path=db_path)
        yield db_path


# 1. Valid purchase
def test_valid_purchase(engine):
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 25000, "category": "electronics", "merchant_id": 1, "merchant_name": "TechMart Electronics"}, daily_spent=0)
    assert result["authorized"] is True
    assert result["requires_approval"] is False
    assert result["violations"] == []

# 2. Amount above maximum
def test_amount_above_maximum(engine):
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 65000, "category": "electronics"}, daily_spent=0)
    assert result["authorized"] is False
    assert "max_transaction_exceeded" in result["violations"]

# 3. Daily limit exceeded
def test_daily_limit_exceeded(engine):
    # Already spent 90k, new 20k -> projected 110k > 100k
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 20000, "category": "electronics"}, daily_spent=90000)
    assert result["authorized"] is False
    assert "daily_limit_exceeded" in result["violations"]

# 4. Blocked category
def test_blocked_category(engine):
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 10000, "category": "gambling"}, daily_spent=0)
    assert result["authorized"] is False
    assert "category_blocked" in result["violations"]

# 5. Allowed category
def test_allowed_category(engine):
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 10000, "category": "books"}, daily_spent=0)
    assert result["authorized"] is True
    assert "category_not_allowed" not in result["violations"]
    assert "category_blocked" not in result["violations"]

# 6. Approval threshold
def test_approval_threshold(engine):
    # 50k > 30k approval threshold, but <60k max, so authorized but requires approval
    result = engine.evaluate(DEFAULT_POLICY, {"amount": 50000, "category": "travel"}, daily_spent=0)
    assert result["authorized"] is True
    assert result["requires_approval"] is True
    # Exactly at threshold should NOT require approval
    result2 = engine.evaluate(DEFAULT_POLICY, {"amount": 30000, "category": "travel"}, daily_spent=0)
    assert result2["requires_approval"] is False
    # Just above
    result3 = engine.evaluate(DEFAULT_POLICY, {"amount": 30001, "category": "travel"}, daily_spent=0)
    assert result3["requires_approval"] is True

# 7. Unauthorized agent (inactive policy)
def test_unauthorized_agent(engine):
    inactive_policy = Policy(
        user_id=1, agent_id=99, daily_limit=100000, max_transaction=60000, approval_threshold=30000,
        allowed_categories=["electronics"], blocked_categories=[], is_active=False
    )
    result = engine.evaluate(inactive_policy, {"amount": 10000, "category": "electronics"}, daily_spent=0)
    assert result["authorized"] is False
    assert "agent_unauthorized" in result["violations"]
    # Missing policy
    result2 = engine.evaluate(None, {"amount": 10000, "category": "electronics"}, daily_spent=0)
    assert result2["authorized"] is False
    assert "missing_policy" in result2["violations"]

# 8. Restricted merchant
def test_restricted_merchant(engine):
    policy_blocked_merchant = Policy(
        user_id=1, agent_id=1, daily_limit=100000, max_transaction=60000, approval_threshold=30000,
        allowed_categories=["electronics", "books", "travel"], blocked_categories=["gambling", "financial_products"],
        blocked_merchants=["BetZone"]
    )
    result = engine.evaluate(policy_blocked_merchant, {"amount": 10000, "category": "electronics", "merchant_name": "BetZone"}, daily_spent=0)
    assert result["authorized"] is False
    assert "merchant_blocked" in result["violations"]

    # Allowed merchants allowlist
    policy_allowlist = Policy(
        user_id=1, agent_id=1, daily_limit=100000, max_transaction=60000, approval_threshold=30000,
        allowed_categories=["electronics"], blocked_categories=[], allowed_merchants=["TechMart Electronics"]
    )
    result2 = engine.evaluate(policy_allowlist, {"amount": 10000, "category": "electronics", "merchant_name": "OtherStore"}, daily_spent=0)
    assert result2["authorized"] is False
    assert "merchant_not_allowed" in result2["violations"]
    result3 = engine.evaluate(policy_allowlist, {"amount": 10000, "category": "electronics", "merchant_name": "TechMart Electronics"}, daily_spent=0)
    assert result3["authorized"] is True

# 9. Missing policy (DB-backed)
def test_missing_policy_db(engine, tmp_db):
    # tmp_db has policy for (1,1) only. Use (1,999)
    # Create a second agent without policy
    agent = repo.create_agent("Untrusted Agent", db_path=tmp_db)
    result = engine.evaluate_request(user_id=1, agent_id=agent["id"], amount=10000, category="electronics", merchant_id=1, db_path=tmp_db)
    assert result["authorized"] is False
    assert any(v in result["violations"] for v in ("missing_policy", "agent_unauthorized", "missing_policy"))

# 10. Invalid payment data
def test_invalid_payment_data(engine):
    result = engine.evaluate(DEFAULT_POLICY, {"amount": -5000, "category": "electronics"}, daily_spent=0)
    assert result["authorized"] is False
    assert "invalid_amount" in result["violations"]
    result2 = engine.evaluate(DEFAULT_POLICY, {"amount": 0, "category": ""}, daily_spent=0)
    assert result2["authorized"] is False
    assert "missing_category" in result2["violations"] or "invalid_amount" in result2["violations"]
    # Category not allowed (food not in allowlist)
    result3 = engine.evaluate(DEFAULT_POLICY, {"amount": 10000, "category": "food"}, daily_spent=0)
    # food is not in allowed [electronics,books,travel] nor blocked, so should be not_allowed
    assert "category_not_allowed" in result3["violations"]

def test_db_backed_valid_flow(tmp_db):
    engine = PolicyEngine()
    # Valid request via DB — uses seeded policy (1,1) daily 100k
    result = engine.evaluate_request(user_id=1, agent_id=1, amount=20000, category="books", merchant_id=2, db_path=tmp_db)
    assert result["authorized"] is True
    assert result["requires_approval"] is False
    assert result["daily_spent"] == 0

def test_db_backed_daily_limit_exceeded(tmp_db):
    engine = PolicyEngine()
    # Insert payments to push daily spent to 90k
    repo.create_payment_request("req_dl_1", 1, 1, 1, "TechMart Electronics", 50000, "INR", "electronics", db_path=tmp_db)
    repo.create_payment_request("req_dl_2", 1, 1, 1, "TechMart Electronics", 40000, "INR", "electronics", db_path=tmp_db)
    result = engine.evaluate_request(user_id=1, agent_id=1, amount=20000, category="electronics", merchant_id=1, db_path=tmp_db)
    assert result["authorized"] is False
    assert "daily_limit_exceeded" in result["violations"]
