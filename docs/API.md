# API.md — PayTrust AI HTTP Service (`api/`)

The tested deterministic engines (`paytrust-ai/`) are exposed as a real REST API so
merchants / AI agents can programmatically consume PayTrust decisions.

**Design rule:** the API adds **no new business logic** — it wraps already-tested
modules (`engines/*`, `models/payment_request.py`, `services/razorpay_service.py`).
Deterministic engines are final; the LLM is advisory only.

## Start

```powershell
pip install -r requirements.txt
python -m api.main            # → http://localhost:8000
```

- Swagger UI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`, readiness: `http://localhost:8000/ready`

## Auth

- `/v1/*` (except `/health`, `/ready`) requires header `X-API-Key: <key>`.
- Key resolution (order):
  1. `PAYTRUST_API_KEY` env var (set this in production).
  2. Dev fallback derived from `SECRET_KEY`: `dev-<sha256(SECRET_KEY)[:16]>` — run
     `python -c "from api.security import api_key_for; print(api_key_for())"` to print it.
- In-process rate limiting (sliding window, `RATE_LIMIT_REQUESTS`/`RATE_LIMIT_WINDOW`
  from config) — no Redis required on a single instance.
- Every response carries `X-Request-ID` (pass yours upstream via the same header for
  end-to-end correlation).

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | – | Liveness probe (db reachable) |
| GET | `/ready` | – | Readiness probe (db + model files) |
| POST | `/v1/evaluate` | API key | Full pipeline → `ALLOW / ASK_USER / DENY` with evidence |
| GET | `/v1/payments?limit=50` | API key | Recent evaluations |
| GET | `/v1/payments/{request_id}` | API key | Payment + decision + risk + audit detail |
| POST | `/v1/webhooks/razorpay` | HMAC | Razorpay test webhook (raw body verified, idempotent) |
| GET | `/v1/evaluation/metrics` | API key | IEEE held-out + synthetic evaluation reports |
| GET | `/v1/threshold?p=0.95` | API key | Classification + SIMULATED cost metrics at one operating point (real IEEE held-out test) |
| GET | `/v1/threshold/curves` | API key | Threshold sweep curves (precision / recall / FPR / costs) |
| GET | `/v1/threshold/recommend` | API key | Suggested operating points (max F1, min SIMULATED cost) |
| GET | `/v1/threshold/check` | API key | Whether test predictions exist (UI gating) |

### POST /v1/evaluate

Body — any valid `PaymentRequest` plus optional `investigate: bool`:

```json
{
  "request_id": "req_api_001",
  "user_id": 1,
  "agent_id": 1,
  "merchant_id": 1,
  "merchant_name": "TechMart Electronics",
  "amount": 25000,
  "currency": "INR",
  "category": "electronics",
  "description": "Laptop",
  "agent_reason": "User requested",
  "investigate": false
}
```

Response highlights:

```json
{
  "request_id": "req_api_001",
  "decision": "ALLOW",
  "risk_score": 11,
  "risk_level": "LOW",
  "reasons": ["..."],
  "policy_result": { "authorized": true, "violations": [], ... },
  "risk_result": { "risk_score": 11, "risk_level": "LOW", "factors": [...] },
  "simulation": { "counterfactuals": [...], "recommended": "...", "disclaimer": "SIMULATED / ESTIMATED ..." },
  "ai": null,
  "processing_ms": 42.1,
  "duplicate": false,
  "simulated_estimates": true,
  "disclaimer": "Decision is deterministic (LLM never overrides). AI explanation is advisory only. ..."
}
```

- **Idempotent:** sending the same `request_id` again reuses the stored payment and
  returns `duplicate: true` with the same deterministic decision.
- `investigate: true` calls the **advisory** AI engine (OpenRouter → Groq → Gemini →
  deterministic fallback). It never changes the decision.
- `simulation.*` values are SIMULATED expected-cost estimates, never real forecasts.

### POST /v1/webhooks/razorpay

- Header `X-Razorpay-Signature` verified with HMAC-SHA256 over the **raw body** before parsing.
- Duplicate `event_id` → `200 {"status": "duplicate"}` (idempotent ignore).
- Invalid/missing signature → `400`.
- Events stored in `razorpay_events` + audit log; see `services/razorpay_service.py`.

### Threshold Decision Tool (Track 02: choose the operating point)

A merchant picks a fraud-probability threshold and sees **real held-out test**
metrics + the **SIMULATED cost trade-off** (fraud exposure vs false-positive
cost) — no fake numbers. Reads `evaluation/ieee_test_predictions.parquet`
saved by `models/train_ieee_chunked.py`. If predictions are missing, these
return `404 {code: NO_TEST_PREDS}`.

```powershell
# Metrics at one operating point
curl -H "X-API-Key: $KEY" "http://localhost:8000/v1/threshold?p=0.95"
# → { threshold, precision, recall, f1, false_positive_rate, tp, fp, tn, fn,
#     blocked_count, allowed_count, fraud_exposure, false_positive_cost,
#     expected_total_cost, currency, disclaimer: "SIMULATED / ESTIMATED ..." }

# Sweep curves (precision/recall/FPR/cost vs threshold)
curl -H "X-API-Key: $KEY" "http://localhost:8000/v1/threshold/curves"

# Operating-point hints (max F1, min SIMULATED total cost) — labeled as hints
curl -H "X-API-Key: $KEY" "http://localhost:8000/v1/threshold/recommend"

# UI gating
curl -H "X-API-Key: $KEY" "http://localhost:8000/v1/threshold/check"
```

All costs are SIMULATED/ESTIMATED (cost model in `core/config.py`) and clearly
labeled — never a financial forecast.

## Errors

All errors follow `{"detail": {"code": "...", "message": "...", ...}}`:

- `401` invalid/missing `X-API-Key`
- `429` rate limit exceeded (header `Retry-After`)
- `422` validation failure (`code: VALIDATION_ERROR`, `errors: [...]`)
- `400` domain rejection (e.g. invalid webhook)
- `404` unknown resource
- `500` unexpected failure (message truncated, never leaks secrets)

## Env vars (see `.env.example`)

```
PAYTRUST_API_KEY=            # empty in dev → derived dev key
CORS_ALLOW_ORIGINS=*         # explicit allowlist in production
```

Production boot guard: `create_app()` refuses to boot if `ENVIRONMENT=production`
with a default `SECRET_KEY`, no `PAYTRUST_API_KEY`, or `CORS_ALLOW_ORIGINS=*`.

## Tests

```powershell
python -m pytest tests/test_api.py -v
```

16 tests: auth, rate-limit wiring, validation 422 contract, idempotency, webhook
HMAC + duplicate + reject, evaluation metrics, request-id, health/ready.

## Deployment

See root `Dockerfile` + `docker-compose.yml` (reference, not required locally) and
`docs/DEPLOYMENT.md` for free Hugging Face Spaces (Docker) / VPS options.