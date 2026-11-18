"""PayTrust as an MCP server: lets any MCP-capable AI agent ask PayTrust before paying.

Run it (stdio transport) from an MCP host's configuration:

    PAYTRUST_API_KEY=pt_…  PAYTRUST_URL=https://paytrust.example.com  paytrust-mcp

Tools
  authorize_payment     ask before paying; returns the decision and what to do next
  get_payment_status    the current state of an earlier request
  wait_for_approval     block (up to a few minutes) until a human approves or rejects

The server never moves money itself. It tells the agent whether it may.
"""
from __future__ import annotations

import os
import sys
from typing import Any

import anyio

from paytrust.client import PayTrust, new_request_id
from paytrust.errors import ApprovalTimeout, PayTrustError, ValidationError
from paytrust.models import Decision

INSTRUCTIONS = """\
PayTrust decides whether you may spend the user's money. Call `authorize_payment` BEFORE every \
payment, and follow `next_step` exactly:
- can_pay = true: you may complete this one payment, for exactly this amount and merchant.
- status PENDING_APPROVAL: do NOT pay. Tell the user a confirmation is needed, then call \
`wait_for_approval` with the request_id.
- refused (DENIED, REJECTED, EXPIRED) or any error: do NOT pay. Tell the user why, using `reasons`.
Never retry a refused payment with a different amount, merchant or category to get around a rule. \
If a call fails because of a network problem, retry it with the SAME request_id.
"""

MAX_WAIT_SECONDS = 600


def _next_step(d: Decision) -> str:
    if d.can_pay:
        order = f" Use order {d.order['id']}." if d.order and d.order.get("id") else ""
        return f"Payment approved. You may pay INR {d.amount:,} to {d.merchant_name} now.{order}"
    if d.waiting_for_approval:
        return ("Do NOT pay yet. A person must approve this payment. Tell the user, then call "
                f"wait_for_approval(request_id='{d.request_id}').")
    return "Do NOT pay. Tell the user it was not allowed and why: " + "; ".join(d.reasons[:3])


def _result(d: Decision) -> dict[str, Any]:
    return {
        "request_id": d.request_id,
        "decision": d.decision,
        "status": d.status,
        "can_pay": d.can_pay,
        "amount_inr": d.amount,
        "merchant": d.merchant_name,
        "reasons": d.reasons[:5],
        "violations": d.violations,
        "risk_level": d.risk_level,
        "expires_at": d.expires_at,
        "order_id": (d.order or {}).get("id"),
        "next_step": _next_step(d),
    }


def _error(exc: PayTrustError) -> dict[str, Any]:
    detail = exc.message
    if isinstance(exc, ValidationError) and exc.details:
        detail += ": " + "; ".join(f"{d.get('field')}: {d.get('message')}" for d in exc.details if isinstance(d, dict))
    return {"can_pay": False, "error": detail, "status_code": exc.status,
            "next_step": "Do NOT pay. PayTrust could not authorize this payment; tell the user."}


def create_server(client: PayTrust) -> Any:
    """Build the MCP server around a PayTrust client (tests pass their own)."""
    from mcp.server.mcpserver import MCPServer
    from mcp_types import ToolAnnotations

    server = MCPServer("paytrust", title="PayTrust payment authorization", instructions=INSTRUCTIONS,
                       version="0.1.0")

    @server.tool(annotations=ToolAnnotations(title="Ask PayTrust before paying", read_only_hint=False,
                                             destructive_hint=False, idempotent_hint=True, open_world_hint=True))
    async def authorize_payment(user_id: int, merchant_id: int, merchant_name: str, amount_inr: int, category: str,
                                description: str, reason: str, request_id: str | None = None) -> dict[str, Any]:
        """Ask PayTrust whether you may make a payment for the user. Call this BEFORE paying.

        Args:
            user_id: the PayTrust id of the user whose money it is
            merchant_id: the PayTrust id of the merchant to pay
            merchant_name: the merchant's name as shown to the user
            amount_inr: whole Indian rupees
            category: e.g. electronics, books, travel, food, fashion, grocery, fuel
            description: what is being bought
            reason: why you are buying it (the user's request, in a sentence)
            request_id: optional idempotency key; reuse the same one when retrying the same payment
        """
        try:
            d = await anyio.to_thread.run_sync(lambda: client.authorize(
                user_id=user_id, merchant_id=merchant_id, merchant_name=merchant_name, amount=amount_inr,
                category=category, description=description, reason=reason,
                request_id=request_id or new_request_id("mcp")))
        except PayTrustError as exc:
            return _error(exc)
        return _result(d)

    @server.tool(annotations=ToolAnnotations(title="Check a payment", read_only_hint=True, open_world_hint=True))
    async def get_payment_status(request_id: str) -> dict[str, Any]:
        """The current state of a payment you asked about earlier (e.g. after the user approved it)."""
        try:
            return _result(await anyio.to_thread.run_sync(lambda: client.get(request_id)))
        except PayTrustError as exc:
            return _error(exc)

    @server.tool(annotations=ToolAnnotations(title="Wait for the user's approval", read_only_hint=True,
                                             open_world_hint=True))
    async def wait_for_approval(request_id: str, timeout_seconds: int = 300) -> dict[str, Any]:
        """Wait until a person approves or rejects a payment that needs approval (at most 10 minutes).

        Only pay if the result says can_pay = true."""
        timeout = max(1, min(int(timeout_seconds), MAX_WAIT_SECONDS))
        try:
            d = await anyio.to_thread.run_sync(lambda: client.wait_for_resolution(request_id, timeout=timeout))
        except ApprovalTimeout:
            return {"request_id": request_id, "status": "PENDING_APPROVAL", "can_pay": False,
                    "next_step": "Still waiting for approval. Do NOT pay. Tell the user, or call wait_for_approval "
                                 "again later."}
        except PayTrustError as exc:
            return _error(exc)
        return _result(d)

    return server


def main() -> None:
    api_key = os.environ.get("PAYTRUST_API_KEY", "")
    if not api_key:
        sys.exit("Set PAYTRUST_API_KEY to the agent's PayTrust API key (pt_…)")
    try:
        import mcp  # noqa: F401
    except ImportError:
        sys.exit("The MCP server needs the optional dependency: pip install 'paytrust[mcp]'")
    client = PayTrust(api_key, os.environ.get("PAYTRUST_URL", "http://127.0.0.1:8000"))
    create_server(client).run("stdio")


if __name__ == "__main__":
    main()
