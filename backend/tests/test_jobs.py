"""Durable background jobs: outbox atomicity, restart survival, retries, dead letters, leases."""
from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app import db
from app.config import get_settings
from app.db import utcnow
from app.errors import ServiceUnavailable
from app.models import AuditEvent, Job, JobStatus, Payment
from app.services import callbacks, jobs, razorpay, tasks
from tests.conftest import payment
from tests.test_callbacks import _FakeClient, _resolve_to


def _jobs(request_id: str) -> list[Job]:
    with db.session_scope() as session:
        return list(session.scalars(select(Job).where(Job.request_id == request_id).order_by(Job.id)))


def _payment(request_id: str) -> Payment:
    with db.session_scope() as session:
        return session.scalar(select(Payment).where(Payment.request_id == request_id))


def _audit(request_id: str) -> list[str]:
    with db.session_scope() as session:
        return list(session.scalars(select(AuditEvent.event_type).where(AuditEvent.request_id == request_id)
                                    .order_by(AuditEvent.id)))


def _later(minutes: float):
    return utcnow() + timedelta(minutes=minutes)


@pytest.fixture
def deferred():
    """Jobs are queued but not run (like a server that is down or restarting)."""
    tasks.run_inline(False)
    yield
    tasks.run_inline(True)


def _flaky_orders(monkeypatch, failures: int):
    calls = {"n": 0, "recovered": False}
    real = razorpay.create_order

    def create_order(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= failures and not calls["recovered"]:
            raise ServiceUnavailable("Razorpay order creation failed: HTTP 503")
        return real(*args, **kwargs)

    monkeypatch.setattr(razorpay, "create_order", create_order)
    return calls


# ── Outbox ──

def test_decisions_queue_their_follow_up_work(client, agent_key):
    allowed = client.post("/v1/payments", json=payment(), headers=agent_key).json()
    pending = client.post("/v1/payments", json=payment(amount=45_000), headers=agent_key).json()
    assert [(j.kind, j.status) for j in _jobs(allowed["request_id"])] == [("order.create", "DONE")]
    assert [(j.kind, j.status) for j in _jobs(pending["request_id"])] == [("ai.investigate", "DONE")]
    denied = client.post("/v1/payments", json=payment(category="gambling"), headers=agent_key).json()
    assert _jobs(denied["request_id"]) == []  # nothing to do for a DENY


def test_queued_work_survives_a_restart(client, agent_key, deferred):
    body = client.post("/v1/payments", json=payment(), headers=agent_key).json()
    rid = body["request_id"]
    assert _payment(rid).order is None
    assert [j.status for j in _jobs(rid)] == [JobStatus.PENDING]  # committed with the decision
    # ...the process dies here. After restart a worker finds the job:
    assert jobs.drain() == 1
    assert _payment(rid).order["id"].startswith("order_sim_")
    assert [j.status for j in _jobs(rid)] == [JobStatus.DONE]


def test_duplicate_enqueue_is_ignored(client, agent_key, deferred):
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    with db.session_scope() as session:
        assert jobs.enqueue(session, "order.create", {"request_id": rid}, request_id=rid,
                            dedupe_key=f"order.create:{rid}") is False
    assert len(_jobs(rid)) == 1


# ── Retries and dead letters ──

def test_failed_order_is_retried_with_backoff_until_it_succeeds(client, agent_key, monkeypatch):
    calls = _flaky_orders(monkeypatch, failures=2)
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    job = _jobs(rid)[0]
    assert job.status == JobStatus.PENDING and job.attempts == 1 and "503" in job.last_error
    assert job.run_after > utcnow()  # backing off, not hammering Razorpay
    assert _payment(rid).order is None

    jobs.drain(now=_later(5))
    assert _jobs(rid)[0].attempts == 2 and _jobs(rid)[0].status == JobStatus.PENDING
    jobs.drain(now=_later(60))
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DONE and job.attempts == 3 and calls["n"] == 3
    assert _payment(rid).order["id"].startswith("order_sim_")
    assert _audit(rid).count("ORDER_CREATED") == 1


def test_order_that_never_succeeds_is_dead_lettered(client, agent_key, monkeypatch):
    _flaky_orders(monkeypatch, failures=10_000)
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    for hours in range(1, 12):
        jobs.drain(now=_later(60 * hours))
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DEAD and job.attempts == get_settings().JOB_MAX_ATTEMPTS
    order = _payment(rid).order
    assert order["status"] == "error" and "503" in order["error"]
    events = _audit(rid)
    assert "JOB_DEAD" in events and "ORDER_FAILED" in events


def test_dead_job_can_be_retried(client, agent_key, monkeypatch):
    calls = _flaky_orders(monkeypatch, failures=10_000)
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    for hours in range(1, 12):
        jobs.drain(now=_later(60 * hours))
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DEAD
    assert _payment(rid).order["status"] == "error"
    calls["recovered"] = True  # Razorpay is back
    jobs.retry_dead(job.id, "admin@paytrust.local")
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DONE and job.attempts == 1
    assert _payment(rid).order["id"].startswith("order_sim_")
    assert "JOB_RETRIED" in _audit(rid)


# ── Leases ──

def test_a_job_whose_worker_died_is_reclaimed_after_its_lease(client, agent_key, deferred):
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    stale = jobs.claim(limit=10)  # a worker claims the job... and crashes before finishing it
    assert len(stale) == 1 and _jobs(rid)[0].status == JobStatus.RUNNING
    assert jobs.drain() == 0  # lease still held: nobody else touches it
    lease = get_settings().JOB_LEASE_SECONDS
    assert jobs.drain(now=utcnow() + timedelta(seconds=lease + 1)) == 1
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DONE and job.attempts == 2
    # The crashed worker comes back late: its outcome must not overwrite the newer one.
    jobs.execute(stale[0])
    job = _jobs(rid)[0]
    assert job.status == JobStatus.DONE and job.attempts == 2


def test_the_worker_thread_runs_queued_jobs(client, agent_key, deferred, monkeypatch):
    monkeypatch.setenv("JOB_POLL_SECONDS", "0.05")
    get_settings.cache_clear()
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    jobs.start_worker()
    try:
        # Wait for the job's final status, not the order: the handler stores the order a moment
        # before the worker records DONE.
        deadline = time.time() + 10
        while time.time() < deadline and _jobs(rid)[0].status != JobStatus.DONE:
            time.sleep(0.05)
    finally:
        jobs.stop_worker(wait=True)  # no worker thread may outlive the test
    assert _jobs(rid)[0].status == JobStatus.DONE
    assert _payment(rid).order is not None


# ── Callbacks ──

def _with_callback(client, agent_key, **kw):
    body = client.post("/v1/payments", json=payment(amount=45_000, callback_url="https://agent.example.com/cb", **kw),
                       headers=agent_key).json()
    assert body["status"] == "PENDING_APPROVAL"
    return body["request_id"]


def test_approval_callback_is_sent_after_the_order_and_carries_it(client, agent_key, admin_headers, monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(callbacks.httpx, "Client", _FakeClient)
    _resolve_to(monkeypatch, "93.184.216.34")
    rid = _with_callback(client, agent_key)
    assert client.post(f"/v1/payments/{rid}/approve", headers=admin_headers).status_code == 200
    sent = json.loads(_FakeClient.calls[0]["content"])
    assert sent["status"] == "APPROVED" and sent["order"]["id"].startswith("order_sim_")
    kinds = [j.kind for j in _jobs(rid)]
    assert kinds == ["ai.investigate", "order.create", "callback.notify"]
    assert all(j.status == JobStatus.DONE for j in _jobs(rid))


class _FlakyAgentServer(_FakeClient):
    """The agent's server fails the first `fail` deliveries with HTTP 500."""
    fail = 1

    def post(self, url, **kwargs):
        _FakeClient.calls.append({"url": url, **kwargs})
        status = 500 if len(_FakeClient.calls) <= _FlakyAgentServer.fail else 200

        class _Resp:
            status_code = status
        return _Resp()


def test_callback_is_retried_until_the_agent_accepts_it(client, agent_key, admin_headers, monkeypatch):
    _FakeClient.calls, _FlakyAgentServer.fail = [], 1
    monkeypatch.setattr(callbacks.httpx, "Client", _FlakyAgentServer)
    _resolve_to(monkeypatch, "93.184.216.34")
    rid = _with_callback(client, agent_key)
    client.post(f"/v1/payments/{rid}/reject", headers=admin_headers)
    cb = next(j for j in _jobs(rid) if j.kind == "callback.notify")
    assert cb.status == JobStatus.PENDING and "HTTP 500" in cb.last_error
    jobs.drain(now=_later(5))
    cb = next(j for j in _jobs(rid) if j.kind == "callback.notify")
    assert cb.status == JobStatus.DONE and cb.attempts == 2 and len(_FakeClient.calls) == 2
    assert "CALLBACK_DELIVERED" in _audit(rid)


def test_callback_gives_up_after_max_attempts(client, agent_key, admin_headers, monkeypatch):
    monkeypatch.setenv("CALLBACK_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    _FakeClient.calls, _FlakyAgentServer.fail = [], 10_000
    monkeypatch.setattr(callbacks.httpx, "Client", _FlakyAgentServer)
    _resolve_to(monkeypatch, "93.184.216.34")
    rid = _with_callback(client, agent_key)
    client.post(f"/v1/payments/{rid}/reject", headers=admin_headers)
    for hours in range(1, 5):
        jobs.drain(now=_later(60 * hours))
    cb = next(j for j in _jobs(rid) if j.kind == "callback.notify")
    assert cb.status == JobStatus.DEAD and cb.attempts == 3 and len(_FakeClient.calls) == 3
    assert "CALLBACK_FAILED" in _audit(rid)


def test_approving_a_just_expired_payment_still_notifies_the_agent(client, agent_key, admin_headers, monkeypatch):
    """Regression: expiry discovered at review time never queued the agent's callback."""
    _FakeClient.calls = []
    monkeypatch.setattr(callbacks.httpx, "Client", _FakeClient)
    _resolve_to(monkeypatch, "93.184.216.34")
    rid = _with_callback(client, agent_key)
    with db.session_scope() as session:
        session.execute(update(Payment).where(Payment.request_id == rid).values(expires_at=utcnow() - timedelta(1)))
    resp = client.post(f"/v1/payments/{rid}/approve", headers=admin_headers)
    assert resp.status_code == 409 and "expired" in resp.text
    assert json.loads(_FakeClient.calls[0]["content"])["status"] == "EXPIRED"


# ── Dead-letter API ──

def _kill_an_order(client, agent_key, monkeypatch):
    calls = _flaky_orders(monkeypatch, failures=10_000)
    rid = client.post("/v1/payments", json=payment(), headers=agent_key).json()["request_id"]
    for hours in range(1, 12):
        jobs.drain(now=_later(60 * hours))
    return rid, calls


def test_dead_letter_api_lists_and_retries(client, agent_key, admin_headers, monkeypatch):
    rid, calls = _kill_an_order(client, agent_key, monkeypatch)
    dead = client.get("/v1/jobs", params={"status": "DEAD"}, headers=admin_headers).json()
    assert dead["total"] == 1 and dead["items"][0]["request_id"] == rid and "503" in dead["items"][0]["last_error"]
    summary = client.get("/v1/jobs/summary", headers=admin_headers).json()
    assert summary["by_status"]["DEAD"] == 1 and summary["by_kind"]["order.create"]["DEAD"] == 1
    assert client.get("/v1/stats", headers=admin_headers).json()["jobs"]["dead"] == 1

    job_id = dead["items"][0]["id"]
    calls["recovered"] = True
    retried = client.post(f"/v1/jobs/{job_id}/retry", headers=admin_headers)
    assert retried.status_code == 200 and retried.json()["status"] == "DONE"
    assert _payment(rid).order["id"].startswith("order_sim_")  # the error marker was replaced
    again = client.post(f"/v1/jobs/{job_id}/retry", headers=admin_headers)
    assert again.status_code == 409  # only dead jobs can be retried
    assert client.post("/v1/jobs/999999/retry", headers=admin_headers).status_code == 404


def test_only_admins_retry_jobs(client, agent_key, admin_headers, monkeypatch):
    rid, _ = _kill_an_order(client, agent_key, monkeypatch)
    resp = client.post("/v1/operators", json={"email": "viewer@example.com", "name": "V", "role": "viewer",
                                              "password": "viewer-pass-123"}, headers=admin_headers)
    assert resp.status_code == 201
    token = client.post("/v1/auth/login", json={"email": "viewer@example.com", "password": "viewer-pass-123"}).json()
    viewer = {"Authorization": f"Bearer {token['access_token']}"}
    job_id = client.get("/v1/jobs", params={"status": "DEAD"}, headers=viewer).json()["items"][0]["id"]
    assert client.post(f"/v1/jobs/{job_id}/retry", headers=viewer).status_code == 403


def test_recovered_order_tells_the_agent_again(client, agent_key, admin_headers, monkeypatch):
    """Approved payment whose order died: the agent hears 'order failed', then 'recovered'."""
    _FakeClient.calls = []
    monkeypatch.setattr(callbacks.httpx, "Client", _FakeClient)
    _resolve_to(monkeypatch, "93.184.216.34")
    calls = _flaky_orders(monkeypatch, failures=10_000)
    rid = _with_callback(client, agent_key)
    client.post(f"/v1/payments/{rid}/approve", headers=admin_headers)
    for hours in range(1, 12):
        jobs.drain(now=_later(60 * hours))
    assert json.loads(_FakeClient.calls[-1]["content"])["order"]["status"] == "error"
    job_id = next(j.id for j in _jobs(rid) if j.kind == "order.create")
    calls["recovered"] = True
    assert client.post(f"/v1/jobs/{job_id}/retry", headers=admin_headers).status_code == 200
    assert len(_FakeClient.calls) == 2
    assert json.loads(_FakeClient.calls[-1]["content"])["order"]["id"].startswith("order_sim_")
