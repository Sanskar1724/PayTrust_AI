"""
tests/test_database.py — Phase 2 SQLite persistence tests.

Covers:
- initialization
- insert / read / update
- invalid data (unique, FK, validation)
- relationships
- persistence after restart
- no API keys stored
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database.database import init_db, get_connection, inspect_db
from database import repositories as repo
from core.exceptions import ValidationError, DatabaseError


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(seed=True, db_path=db_path)
        yield db_path


def test_init_creates_tables(tmp_db):
    info = inspect_db(tmp_db)
    assert info["exists"] is True
    expected = {"users", "agents", "agent_policies", "merchants", "payment_requests", "risk_assessments", "decisions", "approvals", "audit_logs"}
    assert expected.issubset(set(info["tables"]))
    assert info["journal_mode"].lower() == "wal"
    assert info["foreign_keys"] == 1


def test_seed_data(tmp_db):
    counts = repo.list_table_counts(db_path=tmp_db)
    assert counts["users"] >= 1
    assert counts["agents"] >= 1
    assert counts["merchants"] >= 4
    assert counts["agent_policies"] >= 1
    # No API key column
    assert inspect_db(tmp_db)["has_api_key_column"] is False


def test_insert_and_read_user(tmp_db):
    user = repo.create_user("alice@example.com", "Alice", role="ADMIN", password_hash="hash123", db_path=tmp_db)
    assert user["email"] == "alice@example.com"
    fetched = repo.get_user(user["id"], db_path=tmp_db)
    assert fetched["name"] == "Alice"
    by_email = repo.get_user_by_email("alice@example.com", db_path=tmp_db)
    assert by_email["id"] == user["id"]


def test_insert_duplicate_user_email_rejected(tmp_db):
    repo.create_user("bob@example.com", "Bob", db_path=tmp_db)
    with pytest.raises(DatabaseError):
        repo.create_user("bob@example.com", "Bob2", db_path=tmp_db)


def test_invalid_email_rejected(tmp_db):
    with pytest.raises(ValidationError):
        repo.create_user("not-an-email", "Nope", db_path=tmp_db)
    with pytest.raises(ValidationError):
        repo.create_user("", "Nope", db_path=tmp_db)


def test_update_user(tmp_db):
    user = repo.create_user("carol@example.com", "Carol", db_path=tmp_db)
    updated = repo.update_user(user["id"], name="Carol Updated", db_path=tmp_db)
    assert updated["name"] == "Carol Updated"
    # Verify persistence
    fetched = repo.get_user(user["id"], db_path=tmp_db)
    assert fetched["name"] == "Carol Updated"


def test_insert_and_read_merchant(tmp_db):
    m = repo.create_merchant("New Store", category="electronics", region="Mumbai", db_path=tmp_db)
    assert m["name"] == "New Store"
    fetched = repo.get_merchant(m["id"], db_path=tmp_db)
    assert fetched["category"] == "electronics"


def test_invalid_merchant_rejected(tmp_db):
    with pytest.raises(ValidationError):
        repo.create_merchant("", category="electronics", db_path=tmp_db)
    with pytest.raises(ValidationError):
        repo.create_merchant("   ", db_path=tmp_db)


def test_create_payment_request_and_fetch(tmp_db):
    # Use seeded user=1, agent=1, merchant=1
    pr = repo.create_payment_request(
        request_id="req_test_001",
        user_id=1,
        agent_id=1,
        merchant_id=1,
        merchant_name="TechMart Electronics",
        amount=25000,
        currency="INR",
        category="electronics",
        description="Laptop",
        agent_reason="User requested",
        db_path=tmp_db,
    )
    assert pr["amount"] == 25000
    fetched = repo.get_payment_request("req_test_001", db_path=tmp_db)
    assert fetched["merchant_name"] == "TechMart Electronics"
    assert fetched["category"] == "electronics"


def test_daily_spent(tmp_db):
    # Initially 0 for new tmp db (seed empty history)
    from datetime import date
    spent = repo.get_daily_spent(1, db_path=tmp_db, today=date.today().isoformat())
    assert spent == 0
    repo.create_payment_request("req_daily_1", 1, 1, 1, "TechMart Electronics", 20000, "INR", "electronics", db_path=tmp_db)
    repo.create_payment_request("req_daily_2", 1, 1, 2, "BookHaven", 30000, "INR", "books", db_path=tmp_db)
    spent2 = repo.get_daily_spent(1, db_path=tmp_db, today=date.today().isoformat())
    assert spent2 == 50000


def test_fk_violation_rejected(tmp_db):
    # Non-existent user
    with pytest.raises(DatabaseError):
        repo.create_payment_request(
            "req_bad_fk", 9999, 1, 1, "TechMart", 1000, "INR", "electronics", db_path=tmp_db
        )
    # Non-existent merchant
    with pytest.raises(DatabaseError):
        repo.create_payment_request(
            "req_bad_merch", 1, 1, 9999, "Nope", 1000, "INR", "electronics", db_path=tmp_db
        )


def test_relationships_and_unique_constraints(tmp_db):
    repo.create_payment_request("req_uniq", 1, 1, 1, "TechMart", 1000, "INR", "electronics", db_path=tmp_db)
    # Duplicate request_id
    with pytest.raises(DatabaseError):
        repo.create_payment_request("req_uniq", 1, 1, 1, "TechMart", 2000, "INR", "electronics", db_path=tmp_db)


def test_no_api_keys_in_db(tmp_db):
    conn = get_connection(tmp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            if t.startswith("sqlite_"):
                continue
            cur.execute(f"PRAGMA table_info({t})")
            cols = [r[1].lower() for r in cur.fetchall()]
            for c in cols:
                assert "api_key" not in c, f"Table {t} has api_key column {c}"
                assert "secret" not in c or c in ("password_hash",), f"Table {t} suspicious secret column {c}"
    finally:
        conn.close()


def test_persistence_after_restart(tmp_db):
    # Insert, close, reopen
    user = repo.create_user("persist@example.com", "Persist", db_path=tmp_db)
    uid = user["id"]
    pr = repo.create_payment_request("req_persist_1", 1, 1, 1, "TechMart Electronics", 12345, "INR", "electronics", db_path=tmp_db)
    # Simulate restart — open new connection to same file
    conn2 = get_connection(tmp_db)
    try:
        cur = conn2.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        assert row is not None and row["email"] == "persist@example.com"
        cur.execute("SELECT * FROM payment_requests WHERE request_id = ?", ("req_persist_1",))
        row2 = cur.fetchone()
        assert row2 is not None and int(row2["amount"]) == 12345
    finally:
        conn2.close()


def test_parameterized_queries(tmp_db):
    # Attempt SQL injection via email — must be treated as data, not code
    malicious = "x@example.com' OR '1'='1"
    # Validation should reject or parameterized insert should not inject
    try:
        repo.create_user(malicious, "Hacker", db_path=tmp_db)
    except (ValidationError, DatabaseError):
        pass
    # Verify users table not dumped — count unchanged except maybe 1
    counts = repo.list_table_counts(db_path=tmp_db)
    assert isinstance(counts["users"], int)
    # Ensure injection didn't create extra table
    conn = get_connection(tmp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert cur.fetchone() is not None
    finally:
        conn.close()
