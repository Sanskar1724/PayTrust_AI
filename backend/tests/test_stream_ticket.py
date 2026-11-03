"""The live feed is opened with a short-lived, stream-only ticket, never the session token."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.api.deps import operator_from_stream_ticket
from app.errors import Unauthorized
from app.services import security


def _ticket(client, admin_headers):
    resp = client.post("/v1/stream/ticket", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in"] == 60
    return body["ticket"]


def test_ticket_requires_sign_in(client):
    assert client.post("/v1/stream/ticket").status_code == 401


def test_session_token_cannot_open_the_stream(client, admin_headers):
    token = admin_headers["Authorization"].removeprefix("Bearer ")
    assert client.get(f"/v1/stream?token={token}").status_code == 401   # the old way
    assert client.get(f"/v1/stream?ticket={token}").status_code == 401  # wrong token type
    assert client.get("/v1/stream").status_code == 401


def test_ticket_is_useless_as_a_bearer_token(client, admin_headers):
    ticket = _ticket(client, admin_headers)
    assert client.get("/v1/stats", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401


def test_valid_ticket_resolves_the_operator(client, admin_headers):
    ticket = _ticket(client, admin_headers)
    assert operator_from_stream_ticket(ticket).email == "admin@paytrust.local"


def test_expired_ticket_is_rejected(client):
    expired = security._encode("stream", 1, timedelta(seconds=-5))
    assert client.get(f"/v1/stream?ticket={expired}").status_code == 401


def test_ticket_for_a_disabled_operator_is_rejected(client, admin_headers):
    resp = client.post("/v1/operators", json={"email": "reviewer@example.com", "name": "Rev", "role": "reviewer",
                                              "password": "reviewer-pass-123"}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    rev_id = resp.json()["id"]
    ticket = security.create_stream_ticket(rev_id)
    assert client.patch(f"/v1/operators/{rev_id}", json={"is_active": False}, headers=admin_headers).status_code == 200
    with pytest.raises(Unauthorized):
        operator_from_stream_ticket(ticket)
