"""Test fixtures: every test gets a fresh database (SQLite file, or PostgreSQL when
TEST_DATABASE_URL is set) and a TestClient with background tasks run inline."""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("AI_AUTO_INVESTIGATE", "true")
for key in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "REDIS_URL"):
    os.environ[key] = ""
os.environ["RAZORPAY_MODE"] = "simulated"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_test_secret"

from app import db  # noqa: E402
from app.api import deps  # noqa: E402
from app.arena import runner  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services import ai, seed, tasks  # noqa: E402

ADMIN = ("admin@paytrust.local", "admin12345")


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    engine = db.init_engine(url)
    if not url.startswith("sqlite"):
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    db.create_all()
    with db.session_scope() as session:
        seed.bootstrap(session)
    tasks.run_inline(True)
    deps.reset_limiter()
    ai._investigator = ai.Investigator(providers=[])
    yield url
    db.get_engine().dispose()
    get_settings.cache_clear()


@pytest.fixture
def app(database):
    from app.main import create_app

    return create_app(manage_schema=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        runner.client_factory = lambda: TestClient(app)
        yield c


@pytest.fixture
def admin_headers(client):
    resp = client.post("/v1/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def agent_key(client, admin_headers):
    """API key for the seeded 'Shopping Assistant' (agent 1, policy with user 1: daily 100k / max 60k / approval 30k)."""
    resp = client.post("/v1/agents/1/keys", json={"name": "tests"}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    return {"X-API-Key": resp.json()["key"]}


def payment(**overrides):
    body = {
        "request_id": f"req_{uuid.uuid4().hex[:12]}",
        "user_id": 1,
        "merchant_id": 1,
        "merchant_name": "TechMart Electronics",
        "amount": 5_000,
        "category": "electronics",
        "description": "Headphones",
        "agent_reason": "User asked for headphones",
    }
    body.update(overrides)
    return body
