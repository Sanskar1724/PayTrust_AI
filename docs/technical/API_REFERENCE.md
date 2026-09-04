# API Reference — PayTrust AI REST Service

> Base URL (dev): `http://localhost:8000` · OpenAPI UI: `/docs` · All responses JSON.
> Auth: `X-API-Key` header on all `/v1/*` endpoints except webhooks (HMAC-signed).
> All schemas below are the **real** ones — captured live from the running service.

## Authentication

```bash
curl -H "X-API-Key: <key>" http://localhost:8000/v1/payments
```

- Dev key: derived deterministically from `SECRET_KEY` when `PAYTRUST_API_KEY` is unset.
  Print it: `python -c "from api.security import api_key_for; print(api_key_for())"`
- Missing/invalid key → `401 {"detail": {"code": "UNAUTHORIZED", ...}}`

## Endpoints

### Health & Readiness (no auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + DB check → `{"status":"ok","database":{...,"ok":true}}` |
| GET | `/ready` | Readiness: DB + model files → `{"ready":true,"models":{"ieee_model.pkl":true,...}}` |

### POST /v1/evaluate — evaluate a payment

**Request** (all fields required unless noted):

```json
{
  "request_id": "demo_allow_1",
  "user_id": 1,
  "agent_id": 1,
  "merchant_id": 1,
  "amount": 25000,
  "category": "electronics",
  "merchant_name": "Croma",
  "investigate": false,
  "currency": "INR",
  "description": "optional",
  "agent_reason": "optional"
}
```

**Response 200** (key fields):

```json
{
  "request_id": "demo_allow_1",
  "decision": "ALLOW",
  "risk_score": 5,
  "risk_level": "LOW",
  "requires_approval": false,
  "reasons": ["...human-readable evidence lines..."],
  "policy_result": {
    "authorized": true, "requires_approval": false, "violations": [],
    "reasons": ["..."], "policy": {"daily_limit": 100000, "max_transaction": 60000,
    "approval_threshold": 30000, "allowed_categories": [...], "blocked_categories": [...]},
    "daily_spent": 278200
  },
  "risk_result": {"risk_score": 90, "risk_level": "CRITICAL",
    "factors": [{"name": "amount_risk", "severity": "high", "score": 20, "details": "..."}]},
  "simulation": {"counterfactuals": [{"action": "ALLOW", "fraud_exposure": 8250.0,
    "false_positive_cost": 0.0, "operational_cost": 0.0, "customer_friction": "low",
    "policy_violation": true, "expected_total_cost": 8250.0,
    "label": "SIMULATED / ESTIMATED", "rationale": "..."}]},
  "ai": null,
  "processing_ms": 14.9,
  "duplicate": false,
  "simulated_estimates": true,
  "disclaimer": "Decision is deterministic (LLM never overrides). AI explanation is advisory only..."
}
```

- `investigate: true` adds the `ai` block: `explanation, summary, concerns[],
  review_questions[], confidence, provider ("openrouter"|"groq"|"gemini"|"deterministic"),
  model, latency_ms, fallback_used, error`.
- Idempotent: same `request_id` → stored decision replayed with `duplicate: true`.
- Validation failure → `422 {"detail": {"code": "VALIDATION_ERROR",
  "errors": [{"type": "missing", "loc": ["body", "merchant_id"], "msg": "Field required"}]}}`

### GET /v1/payments — list recent evaluations

`GET /v1/payments?limit=50` → `{"items": [{...payment + decision + risk...}], "count": 9}`

### GET /v1/payments/{request_id} — full evidence detail

Returns payment + policy_result + risk_result + decision + audit trail for one `request_id`. 404 if unknown.

### GET /v1/evaluation/metrics — ML metrics

→ `{"ieee": {...}, "synthetic_ml": {...}, "available": true, "disclaimer": "..."}`
(IEEE block includes held-out PR-AUC 0.314, ROC-AUC, confusion matrix from the temporal split.)

### GET /v1/threshold/check · /curves · /recommend — threshold decision tool

- `/check` → `{"available": true, "rows": 3000, "missing": null}` (real held-out rows loaded)
- `/curves` → precision/recall/F1/FPR across thresholds from the 3,000 held-out IEEE rows
- `/recommend` → cost-minimizing threshold under the configured cost model (labeled ESTIMATED)

### POST /v1/webhooks/razorpay — payment events (no API key; HMAC instead)

Headers: `X-Razorpay-Signature: <HMAC-SHA256 of the RAW body using RAZORPAY_WEBHOOK_SECRET>`.
Body: `{"entity": "event", "event": "payment.captured", "id": "evt_demo_1", ...}`
- Valid + first time → `200 {"event_id": "evt_demo_1", "status": "processed", ...}`
- Same `event_id` again → `200 {"status": "duplicate"}` (idempotent)
- Bad signature → rejected; retries beyond `WEBHOOK_MAX_RETRIES` → DLQ (`razorpay_events.status`).

## Error format

All structured errors: `{"detail": {"code": "<MACHINE_CODE>", "message": "...", ...}}`
Codes seen: `VALIDATION_ERROR` (422), `UNAUTHORIZED` (401), `NOT_FOUND` (404),
`AI_PROVIDER_ERROR` (advisory only — decision still deterministic).
