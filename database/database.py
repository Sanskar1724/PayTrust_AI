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
    daily_limit         INTEGER NOT NULL,
    max_transaction     INTEGER NOT NULL,
    approval_threshold  INTEGER NOT NULL,
    allowed_categories  TEXT NOT NULL,
    blocked_categories  TEXT NOT NULL,
    allowed_merchants   TEXT,
    blocked_merchants   TEXT,
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
    amount          INTEGER NOT NULL,
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
    risk_score      INTEGER NOT NULL,
    risk_level      TEXT NOT NULL,
    factors         TEXT NOT NULL,
    model_version   TEXT NOT NULL DEFAULT 'v1-deterministic',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT UNIQUE NOT NULL REFERENCES payment_requests(request_id) ON DELETE CASCADE,
    decision        TEXT NOT NULL,
    risk_score      INTEGER NOT NULL,
    risk_level      TEXT NOT NULL,
    policy_result   TEXT NOT NULL,
    reasons         TEXT NOT NULL,
    ai_explanation  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    approver        TEXT,
    status          TEXT NOT NULL,
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
    metadata        TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS razorpay_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT UNIQUE NOT NULL,
    event_type      TEXT NOT NULL,
    payment_id      TEXT,
    payload_hash    TEXT NOT NULL,
    received_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    processed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_razorpay_events_type ON razorpay_events(event_type);
CREATE INDEX IF NOT EXISTS idx_razorpay_events_status ON razorpay_events(status);

CREATE INDEX IF NOT EXISTS idx_payment_requests_user ON payment_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_agent ON payment_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_payment_requests_created ON payment_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_risk_request ON risk_assessments(request_id);
-- One assessment per payment: dedupe for INSERT OR REPLACE semantics used by app/api.
CREATE UNIQUE INDEX IF NOT EXISTS uq_risk_request ON risk_assessments(request_id);
CREATE INDEX IF NOT EXISTS idx_decisions_decision ON decisions(decision);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_logs(request_id);
"""


def get_db_path() -> Path:
    p = settings.sqlite_path
    if p is None:
        p = Path(__file__).resolve().parents[1] / "data" / "paytrust.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class _ManagedConnection:
    """Thin wrapper: `with get_connection() as conn` now CLOSES on exit.

    (Raw sqlite3.Connection.__exit__ only commits — it never closes the fd,
    so every `with get_connection() as conn:` in app.py/api leaked descriptors
    into 'database is locked' (WAL). This wrapper closes on __exit__ while
    proxying everything else, so all existing call sites are fixed at once.
    Direct `conn = get_connection()` use is unaffected — call .close() as before.)
    """

    def __init__(self, conn: sqlite3.Connection):
        object.__setattr__(self, "_conn", conn)

    def __enter__(self) -> sqlite3.Connection:
        return object.__getattribute__(self, "_conn")

    def __exit__(self, *exc_info) -> bool:
        try:
            object.__getattribute__(self, "_conn").close()
        except Exception:
            pass
        return False

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_conn"), name)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a new sqlite3 connection with sensible defaults.

    Safe to use as `with get_connection() as conn:` (auto-closes) or
    `conn = get_connection()` + explicit `conn.close()`.
    """
    path = db_path if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(path), check_same_thread=False, timeout=10.0)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys=ON;")
    return _ManagedConnection(raw)  # type: ignore[return-value]


@contextmanager
def db_cursor(commit: bool = False, db_path: Path | None = None) -> Generator[sqlite3.Cursor, None, None]:
    conn = get_connection(db_path)
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


def init_db(seed: bool = True, db_path: Path | None = None) -> dict:
    """
    Initialize SQLite DB. Idempotent. Returns status dict.
    If seed=True, insert default user/agent/merchant if empty.
    """
    path = db_path if db_path is not None else get_db_path()
    is_new = not path.exists()
    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        # Migrate existing DBs: dedupe risk_assessments (keep latest) before UNIQUE index enforces it.
        try:
            conn.execute(
                "DELETE FROM risk_assessments WHERE id NOT IN "
                "(SELECT MAX(id) FROM risk_assessments GROUP BY request_id)"
            )
            conn.commit()
        except Exception:
            pass

        if seed:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, name, role, password_hash) VALUES (1, ?, ?, 'ADMIN', 'dev-only-hash')",
                ("test@paytrust.ai", "Test User"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO agents (id, agent_name, description) VALUES (1, 'Shopping Assistant', 'Demo shopping agent')"
            )
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
            # Seed default policy for Test User + Shopping Assistant
            import json as _json
            conn.execute(
                """INSERT OR IGNORE INTO agent_policies
                (id, user_id, agent_id, daily_limit, max_transaction, approval_threshold, allowed_categories, blocked_categories)
                VALUES (1, 1, 1, 100000, 60000, 30000, ?, ?)""",
                (_json.dumps(["electronics", "books", "travel"]), _json.dumps(["gambling", "financial_products"])),
            )
            conn.commit()

        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        counts = {}
        for t in ["users", "agents", "agent_policies", "merchants", "payment_requests", "decisions"]:
            try:
                counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                counts[t] = 0
        logger.info(f"DB initialized at {path} (new={is_new}) tables={len(tables)} counts={counts}")
        return {"db_path": str(path), "is_new": is_new, "tables": tables, "counts": counts, "sqlite_version": sqlite3.sqlite_version}
    except Exception as exc:
        raise DatabaseError(f"init_db failed: {exc}") from exc
    finally:
        conn.close()


def inspect_db(db_path: Path | None = None) -> dict:
    """Return diagnostic info for UI/tests — no secrets."""
    path = db_path if db_path is not None else get_db_path()
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    info: dict = {"db_path": str(path), "exists": exists, "size_bytes": size, "sqlite_version": sqlite3.sqlite_version}
    if not exists:
        return info
    conn = get_connection(path)
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
        # Verify no API keys column exists
        info["has_api_key_column"] = any(
            "api_key" in ",".join([c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]).lower()
            for t in info["tables"] if not t.startswith("sqlite_")
        )
    finally:
        conn.close()
    return info
