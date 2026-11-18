# PayTrust Python SDK and MCP server

Ask PayTrust before your AI agent spends a user's money. PayTrust answers **ALLOW**, **ASK_USER** (a person must confirm) or **DENY**, with the reasons.

```bash
pip install "paytrust @ git+https://github.com/Sanskar1724/PayTrust_AI#subdirectory=sdk/python"          # client
pip install "paytrust[mcp] @ git+https://github.com/Sanskar1724/PayTrust_AI#subdirectory=sdk/python"     # + MCP server
```

You need an agent API key (`pt_…`) from the PayTrust console: **Agents & keys → New key**.

## Python client

```python
from paytrust import PayTrust

pt = PayTrust(api_key="pt_…", base_url="https://paytrust.example.com")

d = pt.authorize(
    user_id=1, merchant_id=7, merchant_name="TechMart Electronics",
    amount=2_999, category="electronics",                 # whole INR
    description="Wireless earbuds", reason="User asked for earbuds under ₹3,500",
    request_id="order-1001",                              # optional: your own id makes retries safe across restarts
)

if d.waiting_for_approval:            # ASK_USER: tell the user, then wait (or use a callback_url)
    d = pt.wait_for_resolution(d.request_id, timeout=600)

if d.can_pay:                         # ALLOWED, or APPROVED by a person
    pay(order=d.order)
else:                                 # DENIED, REJECTED or EXPIRED
    tell_user(d.explain())
```

| | |
|---|---|
| `d.can_pay` | the only signal to move money |
| `d.waiting_for_approval` | a person must decide first; do not pay |
| `d.refused` | denied, rejected or expired; do not pay |
| `d.reasons`, `d.violations`, `d.risk_level` | the evidence behind the decision |

**Retries are safe.** Every attempt of one `authorize()` call reuses the same `request_id`, so PayTrust returns the stored decision instead of deciding (or paying) twice. Network errors, `429` and `5xx` are retried with backoff; `429` honours `Retry-After`.

**Errors** all inherit from `PayTrustError`: `AuthenticationError` (401), `PermissionDenied` (403), `NotFound` (404), `ConflictError` (409, a `request_id` reused for a different payment), `ValidationError` (422), `RateLimitError` (429), `ServerError` (5xx), `ConnectionError`, `ApprovalTimeout`. Each carries `status`, `code`, `details` and `trace_id` (quote it when reporting a problem). **On any error, do not pay.**

### Callbacks

Instead of polling, pass `callback_url=` and PayTrust POSTs the outcome when a pending payment is resolved. Verify it before trusting it:

```python
from paytrust import parse_callback

event = parse_callback(raw_body, request.headers["X-PayTrust-Signature"], WEBHOOK_SECRET)  # raises if forged
```

Use the **raw** request bytes, not re-encoded JSON.

## MCP server

`paytrust-mcp` exposes PayTrust to any MCP-capable agent host over stdio:

| Tool | What it does |
|---|---|
| `authorize_payment` | ask before paying; returns `can_pay`, the reasons and a `next_step` the agent must follow |
| `get_payment_status` | the current state of an earlier request |
| `wait_for_approval` | wait (up to 10 minutes) until a person approves or rejects |

The server's instructions tell the agent: call `authorize_payment` before every payment; pay only when `can_pay` is true; never retry a refused payment with a different amount, merchant or category to get around a rule; on network errors retry with the same `request_id`. The server itself never moves money.

Example host configuration:

```json
{
  "mcpServers": {
    "paytrust": {
      "command": "paytrust-mcp",
      "env": { "PAYTRUST_API_KEY": "pt_…", "PAYTRUST_URL": "https://paytrust.example.com" }
    }
  }
}
```

## Development

```bash
cd sdk/python
pip install -e ".[mcp,test]"
pytest
```

The backend's test suite also runs this SDK against the real PayTrust app (`backend/tests/test_sdk_integration.py`).
