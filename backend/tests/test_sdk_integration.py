"""The Python SDK (sdk/python) against the real PayTrust app, end to end."""
from __future__ import annotations

import sys
from pathlib import Path

import anyio
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk" / "python" / "src"))

from paytrust import PayTrust  # noqa: E402
from paytrust.errors import AuthenticationError, ConflictError  # noqa: E402

from tests.conftest import payment  # noqa: E402


@pytest.fixture
def sdk(client, agent_key):
    return PayTrust(agent_key["X-API-Key"], http_client=client)


def _ask(sdk, **kw):
    body = {k: v for k, v in payment(**kw).items() if k not in ("request_id",)}
    return sdk.authorize(user_id=body["user_id"], merchant_id=body["merchant_id"], merchant_name=body["merchant_name"],
                         amount=body["amount"], category=body["category"], description=body["description"],
                         reason=body["agent_reason"], request_id=kw.get("request_id"))


def test_allowed_payment(sdk):
    d = _ask(sdk)
    assert d.decision == "ALLOW" and d.can_pay and d.is_final
    assert sdk.get(d.request_id).order["id"].startswith("order_sim_")


def test_approval_flow_with_wait(sdk, client, admin_headers):
    d = _ask(sdk, amount=45_000)
    assert d.waiting_for_approval and not d.can_pay and d.expires_at
    assert client.post(f"/v1/payments/{d.request_id}/approve", headers=admin_headers).status_code == 200
    final = sdk.wait_for_resolution(d.request_id, timeout=5, poll_interval=0)
    assert final.status == "APPROVED" and final.can_pay and final.order["id"].startswith("order_sim_")


def test_denied_payment_explains(sdk):
    d = _ask(sdk, category="gambling")
    assert d.refused and not d.can_pay and "category_blocked" in d.violations
    assert d.explain().startswith("Not allowed:")


def test_safe_retry_and_conflict(sdk):
    first = _ask(sdk, request_id="sdk_retry_0001")
    again = _ask(sdk, request_id="sdk_retry_0001")
    assert again.duplicate and again.decision == first.decision
    with pytest.raises(ConflictError):
        _ask(sdk, request_id="sdk_retry_0001", amount=9_999)


def test_bad_key_is_an_authentication_error(client):
    with pytest.raises(AuthenticationError):
        PayTrust("pt_00000000_nope", http_client=client).get("anything")


def test_mcp_tool_against_the_real_app(sdk):
    pytest.importorskip("mcp")
    from paytrust.mcp_server import create_server

    result = anyio.run(create_server(sdk).call_tool, "authorize_payment", {
        "user_id": 1, "merchant_id": 1, "merchant_name": "TechMart Electronics", "amount_inr": 2_999,
        "category": "electronics", "description": "Earbuds", "reason": "User asked for earbuds"})
    out = result.structured_content
    out = out.get("result", out)
    assert out["can_pay"] is True and out["decision"] == "ALLOW" and out["next_step"].startswith("Payment approved")
