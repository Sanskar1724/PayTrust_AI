# Integrations — PayTrust AI

> Every external system, the exact contract, and where the integration lives in code.

## 1. Razorpay (payments — TEST MODE ONLY)

**Direction:** outbound orders + inbound webhooks · **Code:** `services/razorpay_service.py`, `api/routers/webhooks.py`

| Aspect | Contract |
|---|---|
| Auth | `RAZORPAY_KEY_ID` must match `rzp_test_*` (live keys refused — guard in code) |
| Webhook intake | `POST /v1/webhooks/razorpay` |
| Verification | `X-Razorpay-Signature` = HMAC-SHA256(**raw body**, `RAZORPAY_WEBHOOK_SECRET`) — raw bytes, not re-serialized JSON |
| Idempotency | `razorpay_events.payload_hash` unique; duplicate `event_id` → `status=duplicate`, no side effects |
| Retry/DLQ | `WEBHOOK_MAX_RETRIES=3`, `WEBHOOK_RETRY_DELAY=5s`, DLQ capped `WEBHOOK_DLQ_MAX_SIZE=1000` |
| Events handled | `payment.captured`, `payment.failed`, `refund.processed` (event ledger stores full type) |

Live-verified: valid signed event → `processed`; replay → `duplicate` (© 2026-09-02 walkthrough).

## 2. OpenRouter (LLM advisory — primary)

**Direction:** outbound HTTPS · **Code:** `engines/ai_engine.py:OpenRouterProvider`

| Aspect | Contract |
|---|---|
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Auth | `Authorization: Bearer $OPENROUTER_API_KEY` |
| Model routing | `model` + `models[]` fallback chain (`google/gemma-4-31b-it:free` → `google/gemma-4-26b-a4b-it:free` → `openrouter/free`) |
| 429 handling | respect `Retry-After` (≤ 8 s), one retry, then next provider |
| Timeout | 12 s httpx client timeout |
| Circuit breaker | 5 consecutive failures → open 60 s |

Live-verified 2026-09-02: real completion referencing actual `daily_spent` state —
see CONNECTIVITY_AND_OPENROUTER_CHECK.md.

## 3. Groq / Gemini / Ollama (LLM fallbacks)

| Provider | Endpoint | Model | Key |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1/chat/completions` | `llama-3.1-70b-versatile` | `GROQ_API_KEY` |
| Gemini | REST (generativelanguage) | configured | `GEMINI_API_KEY` |
| Ollama | `OLLAMA_BASE_URL` (default `localhost:11434`) | local | none |

Same fact-bound prompt and JSON schema for all — provider swap is invisible to the
product, and `fallback_used: true` is always surfaced in the response.

## 4. IEEE-CIS Fraud Detection dataset (ML evidence)

**Direction:** offline batch · **Code:** `models/` (training), `evaluation/run_evaluation.py`

- 590k transactions, temporal split; class imbalance ~3.5% fraud → PR-AUC is the headline.
- Trained artifacts: `models/ieee_model.pkl`, `models/risk_model.pkl` (loaded by `/ready`).
- Held-out predictions: `evaluation/ieee_test_predictions.parquet` powers the
  threshold tool (`/v1/threshold/curves|recommend`) — 3,000 real test rows, live-verified.
- Raw 1.3 GB CSVs are gitignored; provenance + license documented.

## 5. Streamlit ↔ engine wiring (internal, but a real integration seam)

- Dashboard (`app.py`) calls the **same** `engines/` + `services/` code the REST
  API uses — one decision codebase, two transports. Any API-verified behavior in
  PRACTICAL_WALKTHROUGH.md therefore holds in the UI.

## 6. Not integrated (explicit non-goals for the buildathon scope)

- Slack/PagerDuty alerting (audit log export is the seam)
- Kafka/SQS event buses (webhook ledger + DLQ covers current scale)
- KYC/AML vendors (policy engine accepts merchant risk tiers instead)
