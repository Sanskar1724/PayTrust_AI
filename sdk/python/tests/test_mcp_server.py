"""The MCP server's tools, called in-process against a mocked PayTrust."""
from __future__ import annotations

import json

import anyio
import httpx
import pytest

pytest.importorskip("mcp")

from paytrust import PayTrust  # noqa: E402
from paytrust import client as client_module  # noqa: E402
from paytrust.mcp_server import INSTRUCTIONS, create_server  # noqa: E402
from tests.test_client import KEY, payment  # noqa: E402


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda s: None)


def server_for(handler):
    http = httpx.Client(base_url="https://pt.test", transport=httpx.MockTransport(handler))
    return create_server(PayTrust(KEY, "https://pt.test", http_client=http))


def call(server, name, args):
    result = anyio.run(server.call_tool, name, args)
    assert not getattr(result, "is_error", False), result
    data = getattr(result, "structured_content", None)
    if data is None:  # fall back to the text block
        data = json.loads(result.content[0].text)
    return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data


ARGS = {"user_id": 1, "merchant_id": 7, "merchant_name": "TechMart Electronics", "amount_inr": 2999,
        "category": "electronics", "description": "Earbuds", "reason": "User asked for earbuds"}


def test_tools_and_instructions():
    server = server_for(lambda r: httpx.Response(200, json=payment()))
    tools = {t.name: t for t in anyio.run(server.list_tools)}
    assert set(tools) == {"authorize_payment", "get_payment_status", "wait_for_approval"}
    assert tools["get_payment_status"].annotations.read_only_hint is True
    assert tools["authorize_payment"].annotations.read_only_hint is False
    assert "amount_inr" in tools["authorize_payment"].input_schema["properties"]
    assert "BEFORE every payment" in INSTRUCTIONS and server.instructions == INSTRUCTIONS


def test_allowed_payment_says_go_ahead():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(201, json=payment(order={"id": "order_9"}))

    out = call(server_for(handler), "authorize_payment", ARGS)
    assert seen["amount"] == 2999 and seen["request_id"].startswith("mcp_")
    assert out["can_pay"] is True and out["order_id"] == "order_9"
    assert out["next_step"].startswith("Payment approved")


def test_pending_payment_says_do_not_pay_and_wait():
    out = call(server_for(lambda r: httpx.Response(201, json=payment(status="PENDING_APPROVAL", decision="ASK_USER",
                                                                     request_id="req_7"))),
               "authorize_payment", ARGS)
    assert out["can_pay"] is False and "Do NOT pay yet" in out["next_step"] and "req_7" in out["next_step"]


def test_denied_payment_explains_why():
    out = call(server_for(lambda r: httpx.Response(201, json=payment(
        status="DENIED", decision="DENY", violations=["category_blocked"],
        reasons=["Policy violation: category_blocked.", "Category 'gambling' is blocked by policy."]))),
        "authorize_payment", ARGS | {"category": "gambling"})
    assert out["can_pay"] is False and out["violations"] == ["category_blocked"]
    assert "Do NOT pay" in out["next_step"] and "blocked" in out["next_step"]


def test_paytrust_errors_become_do_not_pay():
    out = call(server_for(lambda r: httpx.Response(401, json={"error": {"message": "Missing or invalid X-API-Key"}})),
               "authorize_payment", ARGS)
    assert out["can_pay"] is False and out["status_code"] == 401 and "Do NOT pay" in out["next_step"]


def test_wait_for_approval_returns_the_final_state():
    states = iter(["PENDING_APPROVAL", "APPROVED"])
    out = call(server_for(lambda r: httpx.Response(200, json=payment(status=next(states), decision="ASK_USER"))),
               "wait_for_approval", {"request_id": "req_1", "timeout_seconds": 30})
    assert out["status"] == "APPROVED" and out["can_pay"] is True


def test_wait_for_approval_timeout_is_not_a_go_ahead():
    from paytrust import ApprovalTimeout

    http = httpx.Client(base_url="https://pt.test", transport=httpx.MockTransport(lambda r: pytest.fail("no call")))
    client = PayTrust(KEY, "https://pt.test", http_client=http)

    def still_pending(request_id, timeout):
        raise ApprovalTimeout(f"{request_id} still pending after {timeout} s")

    client.wait_for_resolution = still_pending  # the person has not decided yet
    out = call(create_server(client), "wait_for_approval", {"request_id": "req_1", "timeout_seconds": 5000})
    assert out["can_pay"] is False and out["status"] == "PENDING_APPROVAL" and "Do NOT pay" in out["next_step"]
