"""
database/database.py — SQLite persistence layer for local prototype.

- Uses parameterized SQL (never string interpolation).
- Single-file `data/paytrust.db` — zero infra.
- Idempotent `init_db()` with journal_mode=WAL.
- Helper to inspect DB status for UI/tests.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from core.config import get_settings
from core.logger import get_logger
from core.exceptions import DatabaseError

logger = get_logger("database")
settings = get_settings()

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'VIEWER',
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS agents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT UNIQUE NOT NULL,
    description     TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS agent_policies (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id            INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    daily_limit         INTEGER NOT NULL,  -- in INR paise or INR; we store INR
    max_transaction     INTEGER NOT NULL,
    approval_threshold  INTEGER NOT NULL,
    allowed_categories  TEXT NOT NULL,     -- JSON array
    blocked_categories  TEXT NOT NULL,     -- JSON array
    allowed_merchants   TEXT,              -- JSON array nullable
    blocked_merchants   TEXT,              -- JSON array nullable
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(user_id, agent_id)
);

CREATE TABLE IF NOT EXISTS merchants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    category    TEXT,
    region      TEXT,
    risk_tier   TEXT DEFAULT 'standard',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS payment_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT UNIQUE NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    merchant_id     INTEGER NOT NULL REFERENCES merchants(id),
    merchant_name   TEXT NOT NULL,
    amount          INTEGER NOT NULL,  -- INR
    currency        TEXT NOT NULL DEFAULT 'INR',
    category        TEXT NOT NULL,
    description     TEXT,
    agent_reason    TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL REFERENCES payment_requests(request_id) ON DELETE CASCADE,
    risk_score      INTEGER NOT NULL,  -- 0-100
    risk_level      TEXT NOT NULL,     -- LOW/MEDIUM/HIGH/CRITICAL
    factors         TEXT NOT NULL,     -- JSON array
    model_version   TEXT NOT NULL DEFAULT 'v1-deterministic',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT UNIQUE NOT NULL REFERENCES payment_requests(request_id) ON DELETE CASCADE,
    decision        TEXT NOT NULL,  -- ALLOW / ASK_USER / DENY
    risk_score      INTEGER NOT NULL,
    risk_level      TEXT NOT NULL,
    policy_result   TEXT NOT NULL,  -- JSON
    reasons         TEXT NOT NULL,  -- JSON array
    ai_explanation  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    approver        TEXT,
    status          TEXT NOT NULL,  -- PENDING / APPROVED / REJECTED
    reason          TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    decided_at      TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT,
    event_type      TEXT NOT NULL,
    actor           TEXT,
    action          TEXT NOT NULL,
    metadata        TEXT,  -- JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_payment_requests_user ON payment_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_agent ON payment_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_created ON payment_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_risk_request ON risk_assessments(request_id);
CREATE INDEX IF NOT EXISTS idx_decisions_decision ON decisions(decision);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_logs(request_id);
"""


def get_db_path() -> Path:
    p = settings.sqlite_path
    if p is None:
        # Fallback to file in data/
        p = Path(__file__).resolve().parents[1] / "data" / "paytrust.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_connection() -> sqlite3.Connection:
    """Return a new sqlite3 connection with sensible defaults."""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Enforce FK
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def db_cursor(commit: bool = False) -> Generator[sqlite3.Cursor, None, None]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception as exc:
        conn.rollback()
        raise DatabaseError(str(exc)) from exc
    finally:
        conn.close()


def init_db(seed: bool = True) -> dict:
    """
    Initialize SQLite DB. Idempotent. Returns status dict.
    If seed=True, insert default user/agent/merchant if empty.
    """
    db_path = get_db_path()
    is_new = not db_path.exists()
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()

        # Seed minimal data for Phase 1 demo (idempotent via INSERT OR IGNORE)
        if seed:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, name, role, password_hash) VALUES (1, ?, ?, 'ADMIN', 'dev-only-hash')",
                ("test@paytrust.ai", "Test User"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO agents (id, agent_name, description) VALUES (1, 'Shopping Assistant', 'Demo shopping agent')",
            )
            # Default merchants
            for mid, name, cat in [
                (1, "TechMart Electronics", "electronics"),
                (2, "BookHaven", "books"),
                (3, "TravelEase", "travel"),
                (4, "BetZone", "gambling"),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO merchants (id, name, category) VALUES (?, ?, ?)",
                    (mid, name, cat),
                )
            conn.commit()

        # Quick stats
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        counts = {}
        for t in ["users", "agents", "merchants", "payment_requests", "decisions"]:
            try:
                counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                counts[t] = 0
        logger.info(f"DB initialized at {db_path} (new={is_new}) tables={len(tables)} counts={counts}")
        return {"db_path": str(db_path), "is_new": is_new, "tables": tables, "counts": counts, "sqlite_version": sqlite3.sqlite_version}
    except Exception as exc:
        raise DatabaseError(f"init_db failed: {exc}") from exc
    finally:
        conn.close()


def inspect_db() -> dict:
    """Return diagnostic info for UI/tests — no secrets."""
    db_path = get_db_path()
    exists = db_path.exists()
    size = db_path.stat().st_size if exists else 0
    info = {"db_path": str(db_path), "exists": exists, "size_bytes": size, "sqlite_version": sqlite3.sqlite_version}
    if not exists:
        return info
    conn = get_connection()
    try:
        cur = conn.cursor()
        info["tables"] = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        info["counts"] = {}
        for t in info["tables"]:
            if t.startswith("sqlite_"):
                continue
            try:
                info["counts"][t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                pass
        info["journal_mode"] = cur.execute("PRAGMA journal_mode").fetchone()[0]
        info["foreign_keys"] = cur.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()
    return info
