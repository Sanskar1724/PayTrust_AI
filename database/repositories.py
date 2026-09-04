"""
database/repositories.py — Parameterized, testable data-access helpers.

All queries use `?` placeholders — no string interpolation — guarding against SQL injection.
Supports optional `db_path` for isolated test databases (Phase 2 testing).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from database.database import db_cursor, get_connection
from core.exceptions import ValidationError, DatabaseError


# ── helpers ──

def _json_list(val: list[str] | None) -> str | None:
    if val is None:
        return None
    return json.dumps(val)


def _parse_json_list(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ── Users ──

def create_user(email: str, name: str, role: str = "VIEWER", password_hash: str = "hash", db_path: Path | None = None) -> dict:
    if not email or "@" not in email:
        raise ValidationError("Invalid email", details={"email": email})
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(
            "INSERT INTO users (email, name, role, password_hash) VALUES (?, ?, ?, ?)",
            (email, name, role, password_hash),
        )
        uid = cur.lastrowid
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        return dict(cur.fetchone())


def get_user(user_id: int, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_user(user_id: int, name: str | None = None, role: str | None = None, db_path: Path | None = None) -> dict | None:
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if role is not None:
        sets.append("role = ?"); params.append(role)
    if not sets:
        return get_user(user_id, db_path)
    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    params.append(user_id)
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", tuple(params))
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ── Agents ──

def create_agent(agent_name: str, description: str | None = None, is_active: bool = True, db_path: Path | None = None) -> dict:
    if not agent_name or not agent_name.strip():
        raise ValidationError("agent_name required")
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(
            "INSERT INTO agents (agent_name, description, is_active) VALUES (?, ?, ?)",
            (agent_name.strip(), description, 1 if is_active else 0),
        )
        aid = cur.lastrowid
        cur.execute("SELECT * FROM agents WHERE id = ?", (aid,))
        return dict(cur.fetchone())


def get_agent(agent_id: int, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_agent_by_name(name: str, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM agents WHERE agent_name = ?", (name,))
        row = cur.fetchone()
        return dict(row) if row else None


# ── Merchants ──

def create_merchant(name: str, category: str | None = None, region: str | None = None, risk_tier: str = "standard", db_path: Path | None = None) -> dict:
    if not name or not name.strip():
        raise ValidationError("merchant name required")
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(
            "INSERT INTO merchants (name, category, region, risk_tier) VALUES (?, ?, ?, ?)",
            (name.strip(), category, region, risk_tier),
        )
        mid = cur.lastrowid
        cur.execute("SELECT * FROM merchants WHERE id = ?", (mid,))
        return dict(cur.fetchone())


def get_merchant(merchant_id: int, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ── Policies ──

def create_policy(
    user_id: int,
    agent_id: int,
    daily_limit: int,
    max_transaction: int,
    approval_threshold: int,
    allowed_categories: list[str],
    blocked_categories: list[str],
    allowed_merchants: list[str] | None = None,
    blocked_merchants: list[str] | None = None,
    db_path: Path | None = None,
) -> dict:
    if daily_limit <= 0 or max_transaction <= 0 or approval_threshold <= 0:
        raise ValidationError("Limits must be positive")
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(
            """INSERT INTO agent_policies
            (user_id, agent_id, daily_limit, max_transaction, approval_threshold, allowed_categories, blocked_categories, allowed_merchants, blocked_merchants)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, agent_id, daily_limit, max_transaction, approval_threshold,
                json.dumps([c.lower() for c in allowed_categories]),
                json.dumps([c.lower() for c in blocked_categories]),
                _json_list(allowed_merchants),
                _json_list(blocked_merchants),
            ),
        )
        pid = cur.lastrowid
        cur.execute("SELECT * FROM agent_policies WHERE id = ?", (pid,))
        return dict(cur.fetchone())


def get_policy(user_id: int, agent_id: int, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute(
            "SELECT * FROM agent_policies WHERE user_id = ? AND agent_id = ? AND is_active = 1",
            (user_id, agent_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["allowed_categories"] = json.loads(d["allowed_categories"]) if d["allowed_categories"] else []
        d["blocked_categories"] = json.loads(d["blocked_categories"]) if d["blocked_categories"] else []
        d["allowed_merchants"] = json.loads(d["allowed_merchants"]) if d.get("allowed_merchants") else None
        d["blocked_merchants"] = json.loads(d["blocked_merchants"]) if d.get("blocked_merchants") else None
        return d


def get_daily_spent(user_id: int, db_path: Path | None = None, today: str | None = None) -> int:
    """Sum of payment_requests.amount for user today (UTC date, matching created_at UTC)."""
    if today is None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()  # YYYY-MM-DD UTC
    with db_cursor(db_path=db_path) as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payment_requests WHERE user_id = ? AND substr(created_at,1,10) = ?",
            (user_id, today),
        )
        return int(cur.fetchone()[0])


# ── Payment Requests ──

def create_payment_request(
    request_id: str,
    user_id: int,
    agent_id: int,
    merchant_id: int,
    merchant_name: str,
    amount: int,
    currency: str,
    category: str,
    description: str | None = None,
    agent_reason: str | None = None,
    db_path: Path | None = None,
) -> dict:
    if amount < 1:
        raise ValidationError("amount must be >=1", details={"amount": amount})
    if currency != "INR":
        raise ValidationError("Only INR supported", details={"currency": currency})
    with db_cursor(commit=True, db_path=db_path) as cur:
        cur.execute(
            """INSERT INTO payment_requests
            (request_id, user_id, agent_id, merchant_id, merchant_name, amount, currency, category, description, agent_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, user_id, agent_id, merchant_id, merchant_name, amount, currency, category.lower(), description, agent_reason),
        )
        cur.execute("SELECT * FROM payment_requests WHERE request_id = ?", (request_id,))
        return dict(cur.fetchone())


def get_payment_request(request_id: str, db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute("SELECT * FROM payment_requests WHERE request_id = ?", (request_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ── Generic helpers for tests/inspection ──

def list_table_counts(db_path: Path | None = None) -> dict[str, int]:
    with db_cursor(db_path=db_path) as cur:
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        counts: dict[str, int] = {}
        for t in tables:
            counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return counts


def fetch_one(query: str, params: tuple[Any, ...] = (), db_path: Path | None = None) -> dict | None:
    with db_cursor(db_path=db_path) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_all(query: str, params: tuple[Any, ...] = (), db_path: Path | None = None) -> list[dict]:
    with db_cursor(db_path=db_path) as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def table_has_column(table: str, column_substr: str, db_path: Path | None = None) -> bool:
    with db_cursor(db_path=db_path) as cur:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return any(column_substr.lower() in c.lower() for c in cols)
