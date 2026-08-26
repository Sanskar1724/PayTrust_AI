"""
database/repositories.py — Thin helpers over parameterized SQLite queries.
Phase 2 will add full CRUD; Phase 1 provides just enough for health checks.
"""
from __future__ import annotations

import json
from typing import Any

from database.database import db_cursor


def list_table_counts() -> dict[str, int]:
    with db_cursor() as cur:
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        counts: dict[str, int] = {}
        for t in tables:
            counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return counts


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict | None:
    with db_cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
