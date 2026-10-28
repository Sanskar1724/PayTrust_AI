# Agent integration guide

The full interactive reference is at `/docs` (OpenAPI) on any running instance.

## 1. Get credentials

An admin creates the agent and an API key in the console (**Agents & keys**), and a policy for each user the agent may spend for (**Policies**). The key is shown once.

## 2. Ask before every payment

```http
POST /v1/payments
X-API-Key: pt_1a2b3c4d_...
Content-Type: application/json

{
  "request_id": "order_7f3a91c2",
  "user_id": 1,
  "merchant_id": 1,
  "merchant_name": "TechMart Electronics",
  "amount": 25000,
  "currency": "INR",
  "category": "electronics",
  "description": "Laptop, 16GB RAM",
  "agent_reason": "User asked for a laptop under INR 30,000",
  "callback_url": "https://agent.example.com/paytrust"
}
```

`request_id` is your idempotency key. If you retry after a timeout, send the same id and body. You get the original decision back with HTTP 200 instead of 201. Reusing an id with a different body returns 409.

Response (abridged):

```json
{
  "request_id": "order_7f3a91c2",
  "decision": "ALLOW",
  "status": "ALLOWED",
  "risk_score": 22,
  "risk_level": "LOW",
  "reasons": ["Low risk (22) and within policy."],
  "policy_result": { "violations": [], "daily_spent": 0, "policy": { "daily_limit": 100000 } },
  "risk_result": { "factors": [{ "name": "amount_risk", "severity": "low", "score": 5, "details": "..." }] },
  "order": null,
  "expires_at": null,
  "processing_ms": 6.4
}
```

| `decision` | What the agent should do |
|---|---|
| `ALLOW` | Proceed. An order is attached shortly; fetch it with `GET /v1/payments/{request_id}`. |
| `ASK_USER` | Do not pay yet. `status` is `PENDING_APPROVAL` until a human decides or `expires_at` passes. |
| `DENY` | Do not pay. Show the user the `reasons`. |

## 3. Learn the outcome of ASK_USER

Either poll `GET /v1/payments/{request_id}` until `status` is `APPROVED`, `REJECTED` or `EXPIRED`, or receive a callback:

```http
POST <callback_url>
X-PayTrust-Signature: <hex HMAC-SHA256 of the raw body, keyed with your agent's webhook secret>

{"event":"payment.resolved","request_id":"order_7f3a91c2","status":"APPROVED","decision":"ASK_USER","order":{"id":"order_..."}}
```

Verify the signature before trusting the body:

```python
import hashlib, hmac
expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-PayTrust-Signature"])
```

## Errors

Every error has the same shape:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "request_id": "…", "details": [{"field": "amount", "message": "…"}]}}
```

| Status | Code | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing, invalid or revoked key, or a disabled agent |
| 404 | `NOT_FOUND` | Unknown request id (agents only see their own payments) |
| 409 | `CONFLICT` | `request_id` reused with a different body |
| 422 | `VALIDATION_ERROR` | Bad input; see `details` |
| 429 | `RATE_LIMITED` | Back off for `Retry-After` seconds |
| 5xx | — | No decision was made. Retry with the same `request_id`. |
