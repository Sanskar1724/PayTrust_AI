"""Agent callbacks: signed delivery, and SSRF protection on every callback URL."""
from __future__ import annotations

import hashlib
import hmac
import socket

import pytest
from sqlalchemy import select

from app import db
from app.config import get_settings
from app.models import Agent, AuditEvent
from app.services import callbacks, netguard
from app.services.netguard import UnsafeUrl, check_callback_url, pin_public_address
from tests.conftest import payment

UNSAFE_URLS = [
    "http://localhost:5432/",
    "http://api.localhost/",
    "http://127.0.0.1/",
    "http://10.0.0.5/hook",
    "http://172.16.3.4/",
    "http://192.168.1.10/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://100.64.0.1/",                        # carrier-grade NAT
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",                # IPv4-mapped loopback
    "http://[fd00::1]/",
    "http://metadata.google.internal/",
    "http://printer.local/",
    "http://intranet/",                           # single-label host
    "https://user:pw@agent.example.com/",
    "ftp://agent.example.com/",
    "javascript:alert(1)",
    "https://agent.example.com:0/",
]


@pytest.mark.parametrize("url", UNSAFE_URLS)
def test_unsafe_callback_urls_are_rejected(url):
    with pytest.raises(UnsafeUrl):
        check_callback_url(url)


@pytest.mark.parametrize("url", ["https://agent.example.com/paytrust", "http://93.184.216.34:8080/cb"])
def test_public_callback_urls_are_accepted(url):
    assert check_callback_url(url) == url


def _resolve_to(monkeypatch, *ips):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in ips]
    monkeypatch.setattr(netguard.socket, "getaddrinfo", fake_getaddrinfo)


def test_pinning_refuses_a_host_that_resolves_privately(monkeypatch):
    """DNS rebinding / internal DNS: a public-looking name that points inside."""
    _resolve_to(monkeypatch, "93.184.216.34", "10.1.2.3")  # ANY private answer is enough to refuse
    with pytest.raises(UnsafeUrl, match="non-public"):
        pin_public_address("https://agent.example.com/cb")


def test_pinning_connects_to_the_vetted_ip(monkeypatch):
    _resolve_to(monkeypatch, "2606:2800:220:1::1", "93.184.216.34")
    pinned = pin_public_address("https://agent.example.com:8443/cb?x=1")
    assert pinned.url == "https://93.184.216.34:8443/cb?x=1"  # IPv4 preferred
    assert pinned.host == "agent.example.com"
    assert pinned.host_header == "agent.example.com:8443"


def test_api_rejects_private_callback_urls(client, agent_key, admin_headers):
    resp = client.post("/v1/payments", json=payment(callback_url="http://169.254.169.254/latest"), headers=agent_key)
    assert resp.status_code == 422
    resp = client.post("/v1/agents", json={"name": "Probe", "callback_url": "http://localhost:5432"},
                       headers=admin_headers)
    assert resp.status_code == 422
    resp = client.patch("/v1/agents/1", json={"callback_url": "http://10.0.0.8/"}, headers=admin_headers)
    assert resp.status_code == 422
    # An empty value clears the callback.
    resp = client.patch("/v1/agents/1", json={"callback_url": ""}, headers=admin_headers)
    assert resp.status_code == 200 and resp.json()["callback_url"] is None


class _FakeClient:
    """Stands in for httpx.Client and records what would have been sent."""
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        _FakeClient.calls.append({"url": url, "client": self.kwargs, **kwargs})

        class _Resp:
            status_code = 200
        return _Resp()


def _audit_events(request_id):
    with db.session_scope() as session:
        return [(e.event_type, e.data) for e in
                session.scalars(select(AuditEvent).where(AuditEvent.request_id == request_id))]


def _pending_payment(client, agent_key, **kw):
    body = client.post("/v1/payments", json=payment(amount=45_000, **kw), headers=agent_key).json()
    assert body["status"] == "PENDING_APPROVAL"
    return body["request_id"]


def test_callback_is_signed_and_sent_to_the_pinned_ip(client, agent_key, admin_headers, monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(callbacks.httpx, "Client", _FakeClient)
    _resolve_to(monkeypatch, "93.184.216.34")
    rid = _pending_payment(client, agent_key, callback_url="https://agent.example.com/paytrust")
    assert client.post(f"/v1/payments/{rid}/reject", headers=admin_headers).status_code == 200

    assert len(_FakeClient.calls) == 1
    call = _FakeClient.calls[0]
    assert call["url"] == "https://93.184.216.34/paytrust"
    assert call["headers"]["Host"] == "agent.example.com"
    assert call["extensions"] == {"sni_hostname": "agent.example.com"}
    assert call["client"]["follow_redirects"] is False
    with db.session_scope() as session:
        secret = session.get(Agent, 1).webhook_secret
    expected = hmac.new(secret.encode(), call["content"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-PayTrust-Signature"] == expected
    assert "CALLBACK_DELIVERED" in [t for t, _ in _audit_events(rid)]


def test_callback_to_a_privately_resolving_host_is_blocked(client, agent_key, admin_headers, monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(callbacks.httpx, "Client", _FakeClient)
    _resolve_to(monkeypatch, "169.254.169.254")
    rid = _pending_payment(client, agent_key, callback_url="https://rebind.example.com/cb")
    assert client.post(f"/v1/payments/{rid}/reject", headers=admin_headers).status_code == 200

    assert _FakeClient.calls == []  # nothing was sent
    blocked = [d for t, d in _audit_events(rid) if t == "CALLBACK_BLOCKED"]
    assert blocked and "non-public" in blocked[0]["detail"]


def test_private_networks_flag_is_a_production_problem(monkeypatch):
    monkeypatch.setenv("CALLBACK_ALLOW_PRIVATE_NETWORKS", "true")
    get_settings.cache_clear()
    try:
        assert any("CALLBACK_ALLOW_PRIVATE_NETWORKS" in p for p in get_settings().production_problems())
        assert check_callback_url("http://localhost:9000/cb")  # allowed for local development
    finally:
        monkeypatch.delenv("CALLBACK_ALLOW_PRIVATE_NETWORKS")
        get_settings.cache_clear()
