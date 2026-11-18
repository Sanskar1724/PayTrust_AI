"""Policy history: every rule change is a numbered version; each payment records its version."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select, text

from app import db
from app.models import Payment, Policy, PolicyVersion
from tests.conftest import payment

BACKEND = Path(__file__).resolve().parents[1]
POLICY = {"user_id": 1, "agent_id": 1, "daily_limit": 100_000, "max_transaction": 60_000,
          "approval_threshold": 30_000, "allowed_categories": ["electronics", "books"],
          "blocked_categories": ["gambling"]}


def _versions(client, admin_headers, user_id=1, agent_id=1):
    resp = client.get(f"/v1/policies/{user_id}/{agent_id}/versions", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_seeded_policies_start_at_version_1(client, admin_headers):
    """Policies created outside the API (seed data, Arena) are versioned too."""
    history = _versions(client, admin_headers)
    assert [v["version"] for v in history] == [1]
    assert history[0]["rules"]["daily_limit"] == 100_000 and history[0]["updated_by"] == "seed"


def test_each_change_is_a_new_version_and_identical_saves_are_not(client, admin_headers):
    first = client.put("/v1/policies", json=POLICY | {"daily_limit": 90_000}, headers=admin_headers).json()
    assert first["version"] == 2
    same = client.put("/v1/policies", json=POLICY | {"daily_limit": 90_000}, headers=admin_headers).json()
    assert same["version"] == 2  # nothing changed: no new version
    third = client.put("/v1/policies", json=POLICY | {"daily_limit": 90_000, "allowed_days": ["mon"]},
                       headers=admin_headers).json()
    assert third["version"] == 3
    history = _versions(client, admin_headers)
    assert [v["version"] for v in history] == [3, 2, 1]  # newest first
    assert history[0]["rules"]["allowed_days"] == ["mon"] and history[1]["rules"]["allowed_days"] is None
    assert history[0]["updated_by"] == "admin@paytrust.local"


def test_payments_keep_the_version_that_decided_them(client, agent_key, admin_headers):
    before = client.post("/v1/payments", json=payment(amount=5_000), headers=agent_key).json()
    client.put("/v1/policies", json=POLICY | {"max_transaction": 4_000, "approval_threshold": 4_000},
               headers=admin_headers)
    after = client.post("/v1/payments", json=payment(amount=5_000, description="again"), headers=agent_key).json()
    assert before["policy_result"]["policy_version"] == 1 and before["decision"] == "ALLOW"
    assert after["policy_result"]["policy_version"] == 2 and after["decision"] == "DENY"
    with db.session_scope() as session:
        stored = {p.request_id: p.policy_version for p in session.scalars(select(Payment))}
    assert stored[before["request_id"]] == 1 and stored[after["request_id"]] == 2
    # Version 1's rules are still there to explain the first decision.
    v1 = next(v for v in _versions(client, admin_headers) if v["version"] == 1)
    assert v1["rules"]["max_transaction"] == 60_000


def test_versions_endpoint_404_without_a_policy(client, admin_headers):
    assert client.get("/v1/policies/1/999/versions", headers=admin_headers).status_code == 404


def test_version_rows_are_written_in_the_same_transaction(client, admin_headers):
    with db.session_scope() as session:
        policy = session.scalar(select(Policy).where(Policy.user_id == 1, Policy.agent_id == 1))
        policy.daily_limit = 70_000
    with db.session_scope() as session:
        policy = session.scalar(select(Policy).where(Policy.user_id == 1, Policy.agent_id == 1))
        latest = session.scalar(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id)
                                .order_by(PolicyVersion.version.desc()))
        assert policy.version == 2 and latest.version == 2 and latest.rules["daily_limit"] == 70_000


def test_migration_backfills_version_1_for_existing_policies(tmp_path, monkeypatch):
    """Upgrading a database that already has policies gives each one a version-1 copy."""
    from alembic.config import Config

    from alembic import command
    from app.config import get_settings

    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    db.init_engine(url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    try:
        command.upgrade(cfg, "0007")
        with db.get_engine().begin() as conn:
            conn.execute(text("INSERT INTO users (id, name, created_at) VALUES (1, 'Asha', '2026-11-01')"))
            conn.execute(text("INSERT INTO agents (id, name, webhook_secret, is_active, created_at) "
                              "VALUES (1, 'Bot', 's', 1, '2026-11-01')"))
            conn.execute(text(
                "INSERT INTO policies (user_id, agent_id, daily_limit, max_transaction, approval_threshold, "
                "allowed_categories, blocked_categories, is_active, updated_at, updated_by) "
                "VALUES (1, 1, 12345, 5000, 4000, '[\"books\"]', '[]', 1, '2026-11-01', 'old-admin')"))
        command.upgrade(cfg, "head")
        with db.get_engine().connect() as conn:
            version = conn.execute(text("SELECT version FROM policies")).scalar_one()
            rows = conn.execute(text("SELECT version, rules, updated_by FROM policy_versions")).all()
        assert version == 1 and len(rows) == 1
        rules = rows[0][1] if isinstance(rows[0][1], dict) else json.loads(rows[0][1])
        assert rows[0][0] == 1 and rows[0][2] == "old-admin"
        assert rules["daily_limit"] == 12345 and rules["allowed_categories"] == ["books"]
        command.downgrade(cfg, "0007")  # and back down cleanly
    finally:
        db.get_engine().dispose()
        get_settings.cache_clear()
