"""PayTrust client against a mocked HTTP transport."""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from paytrust import (
    ApprovalTimeout,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    PayTrust,
    PayTrustError,
    RateLimitError,
    ServerError,
    ValidationError,
    parse_callback,
    verify_callback,
)
from paytrust import client as client_module

KEY = "pt_abcd1234_secret"


def payment(status="ALLOWED", decision="ALLOW", **kw):
    return {"request_id": kw.pop("request_id", "req_1"), "decision": decision, "status": status, "amount": 2999,
            "merchant_name": "TechMart Electronics", "risk_score": 10, "risk_level": "LOW",
            "reasons": kw.pop("reasons", ["Low risk (10) and within policy."]),
            "policy_result": {"violations": kw.pop("violations", [])}, "expires_at": None,
            "order": kw.pop("order", None), "duplicate": False, **kw}


def make(handler, **kw) -> PayTrust:
    http = httpx.Client(base_url="https://pt.test", transport=httpx.MockTransport(handler))
    return PayTrust(KEY, "https://pt.test", http_client=http, **kw)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda s: None)


def test_authorize_sends_the_payment_and_reads_the_decision():
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers["X-API-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json=payment(order={"id": "order_1"}))

    d = make(handler).authorize(user_id=1, merchant_id=7, merchant_name="TechMart Electronics", amount=2999,
                                category="electronics", description="Earbuds", reason="User asked")
    assert seen["key"] == KEY
    assert seen["body"]["amount"] == 2999 and seen["body"]["agent_reason"] == "User asked"
    assert seen["body"]["request_id"].startswith("pt_")
    assert d.can_pay and d.is_final and not d.waiting_for_approval and d.order["id"] == "order_1"


def test_decision_helpers():
    from paytrust import Decision
    pending = Decision.from_response(payment(status="PENDING_APPROVAL", decision="ASK_USER",
                                             reasons=["Medium risk (45) — the user should confirm."]))
    assert pending.waiting_for_approval and not pending.can_pay and not pending.is_final
    assert pending.explain().startswith("Waiting for approval: Medium risk")
    denied = Decision.from_response(payment(status="DENIED", decision="DENY", violations=["category_blocked"]))
    assert denied.refused and not denied.can_pay and denied.violations == ["category_blocked"]
    approved = Decision.from_response(payment(status="APPROVED", decision="ASK_USER"))
    assert approved.can_pay and approved.explain() == "Approved by a reviewer"


def test_retries_reuse_the_same_request_id():
    ids, calls = [], {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        ids.append(json.loads(request.content)["request_id"])
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"code": "UNAVAILABLE", "message": "busy"}})
        return httpx.Response(201, json=payment())

    d = make(handler).authorize(user_id=1, merchant_id=7, merchant_name="M", amount=100, category="books")
    assert d.can_pay and calls["n"] == 3
    assert len(set(ids)) == 1  # the same idempotency key every time: PayTrust can never decide twice


def test_network_errors_are_retried_then_reported():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ConnectionError):
        make(handler, max_retries=2).get("req_1")
    assert calls["n"] == 3


def test_rate_limit_honours_retry_after(monkeypatch):
    waits = []
    monkeypatch.setattr(client_module.time, "sleep", waits.append)
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"message": "slow down"}}),
                      httpx.Response(200, json=payment())])
    assert make(lambda r: next(responses)).get("req_1").can_pay
    assert waits == [7.0]


def test_rate_limit_error_after_retries():
    with pytest.raises(RateLimitError) as exc:
        make(lambda r: httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"message": "slow"}}),
             max_retries=1).get("x")
    assert exc.value.retry_after == 3.0


@pytest.mark.parametrize("status,error", [(401, AuthenticationError), (409, ConflictError), (422, ValidationError),
                                          (500, ServerError), (418, PayTrustError)])
def test_error_mapping(status, error):
    body = {"error": {"code": "X", "message": "nope", "details": [{"field": "amount", "message": "bad"}]}}
    with pytest.raises(error) as exc:
        make(lambda r: httpx.Response(status, json=body, headers={"X-Request-ID": "trace1"}), max_retries=0).get("x")
    assert exc.value.status == status and exc.value.trace_id == "trace1" and "nope" in str(exc.value)


def test_validation_errors_are_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(422, json={"error": {"message": "invalid"}})

    with pytest.raises(ValidationError):
        make(handler).get("x")
    assert calls["n"] == 1


def test_wait_for_resolution_polls_until_final():
    states = iter(["PENDING_APPROVAL", "PENDING_APPROVAL", "APPROVED"])
    d = make(lambda r: httpx.Response(200, json=payment(status=next(states), decision="ASK_USER"))) \
        .wait_for_resolution("req_1", timeout=60, poll_interval=0)
    assert d.status == "APPROVED" and d.can_pay


def test_wait_for_resolution_times_out():
    with pytest.raises(ApprovalTimeout):
        make(lambda r: httpx.Response(200, json=payment(status="PENDING_APPROVAL", decision="ASK_USER"))) \
            .wait_for_resolution("req_1", timeout=0, poll_interval=0)


def test_rejects_bad_input_before_calling():
    with pytest.raises(ValueError):
        PayTrust("not-a-key")
    pt = make(lambda r: pytest.fail("must not call PayTrust"))
    for bad in (0, -5, 1.5, True):
        with pytest.raises(ValueError):
            pt.authorize(user_id=1, merchant_id=1, merchant_name="M", amount=bad, category="books")


def test_callback_signatures():
    secret, raw = "whsec_test", b'{"event":"payment.resolved","status":"APPROVED"}'
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_callback(raw, good, secret)
    assert not verify_callback(raw, good, "other")
    assert not verify_callback(raw + b" ", good, secret)  # any change to the body breaks it
    assert not verify_callback(raw, None, secret)
    assert parse_callback(raw, good, secret)["status"] == "APPROVED"
    with pytest.raises(PayTrustError):
        parse_callback(raw, "00", secret)
