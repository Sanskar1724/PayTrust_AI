# SECURITY.md — Phase 13

This is a **production-minded local prototype** — not a certified production system — but it implements defense-minded controls for secrets, injection, webhooks, and audit.

## 1. Secret Management

- Secrets only in `.env` (never in DB, UI, logs, or git). `.gitignore:1` ignores `.env`; `.env.example` is the template.
- `core/config.py:36` reads `RAZORPAY_KEY_ID` (must be `rzp_test_*`), `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `OPENROUTER/GROQ/GEMINI` keys. `validate_for_production()` warns on default `SECRET_KEY` or live Razorpay keys.
- `core/logger.py:18` `RedactingFormatter` redacts `api_key`, `secret`, `sk-or-v1-`, `rzp_test_`, `gsk_` in all logs.
- `core/security.py:assert_no_secrets_in_db` scans SQLite for `api_key`/`secret` columns — `tests/test_security.py:test_no_secrets_in_db` enforces.
- `database/database.py` has no `api_key` columns; `tests/test_database.py:test_no_api_keys_in_db` checks.

**Check:** `python -m core.security` or `security_checklist()` returns `no_secrets_in_db: pass`.

## 2. Input Validation

- `models/payment_request.py:1` Pydantic: `request_id` regex `^[A-Za-z0-9_\-]{6,64}$`, `amount` 1..10_000_000, `currency` only `INR`, `category` enum (9 values), `timestamp` ISO8601 normalized to UTC `Z`, truncates `description` 500.
- `database/repositories.py:1` validates email (`"@"`), merchant name non-empty, policy limits >0, amount ≥1.
- `tests/test_payment_validation.py:1` covers negative, zero, too-large, invalid currency/category, missing user/agent, malformed request_id/timestamp.

## 3. SQL Injection Prevention

- All queries use `?` placeholders via `database/database.py:db_cursor` and `repositories.py` — no f-string interpolation with user input.
- `tests/test_security.py:test_sql_injection_via_parameterized` inserts `Robert'); DROP TABLE merchants; --` as literal and verifies table still exists.

## 4. Safe Logging & Exceptions

- `core/logger.py:RedactingFormatter` + `core/security.py:sanitize_for_log` (truncate 500, redact tokens).
- `core/exceptions.py:1` typed hierarchy (`PayTrustError`, `ValidationError`, `PolicyError`, `DatabaseError`, etc.) — UI catches and shows safe `code` without stack trace leakage.
- `core/logger.py:log_event` filters `secret`/`api_key` keys from `extra`.

## 5. Authorization Boundaries

- `PolicyEngine` deterministic; `DecisionEngine` hard `DENY` on violation — LLM cannot override (`docs/DECISION_ENGINE.md`).
- In future (Postgres track), JWT + RBAC (`ADMIN/OPERATOR/ANALYST/VIEWER`) — here local prototype uses seeded `test@paytrust.ai` / `Shopping Assistant` with policy allowlist.

## 6. Audit Logging

- `database/database.py:118` `audit_logs(request_id, event_type, actor, action, metadata)`; `core/security.py:audit_log` helper redacts secrets and logs structured event.
- Logged: `PAYMENT_CREATED`, `PAYMENT_EVALUATED`, `WEBHOOK_RECEIVED`, `AI_INVESTIGATION`, threshold changes.
- `tests/test_security.py:test_audit_log_redacts_secrets` verifies redaction.
- UI `app.py:Audit Log` shows `request_id, event_type, actor, action, created_at`.

## 7. Razorpay Webhook Security (Phase 11)

- `services/razorpay_service.py:verify_webhook_signature` uses `hmac.new(secret, raw_body, sha256).hexdigest()` + `hmac.compare_digest` (constant-time) over **raw body** before JSON parse (`services/razorpay_service.py:handle_webhook`).
- Idempotency: `razorpay_events.event_id UNIQUE` + `payload_hash`; `is_duplicate_event` checks `event_id` existence; `handle_webhook` returns `{"status":"duplicate"}` on replays (`services/razorpay_service.py:is_duplicate_event`).
- Retry: caller should retry with exponential backoff; failed events stored with `status=PROCESSED|FAILED` and `error_message`. DLQ: query `SELECT * FROM razorpay_events WHERE status='FAILED'`.
- Test: `tests/test_razorpay.py:1` covers correct sig, raw-body vs parsed, `payload_hash`, duplicate, invalid sig rejected, invalid JSON.

## 8. Invalid Payment Handling

- Negative/zero/too-large amounts rejected at Pydantic and policy layers.
- Missing `user_id`/`agent_id` → `missing_user`/`unauthorized_agent` violation → `DENY`.
- Payment actions: **TEST MODE / SIMULATED only** (`services/razorpay_service.py:create_test_order` returns `simulated=True` if keys missing; `app.py:Payment Request` persists decision as `PENDING` unless ALLOW).

## 9. Idempotency & Duplicate Webhook Handling

- `razorpay_events` `event_id UNIQUE` prevents double-processing.
- `payment_requests.request_id UNIQUE` prevents double payment creation.
- `decisions.request_id UNIQUE` prevents double decision.

## 10. Checklist (for Buildathon Demo)

Run `python -c "from core.security import security_checklist; import json; print(json.dumps(security_checklist(), indent=2))"` — all checks should `pass`.

## 11. Limitations (Honest)

- Local prototype — no JWT auth, no rate limiting, no TLS termination (but `core/config.py:RATE_LIMIT_*` and webhook HMAC are ready for Postgres track).
- No live Razorpay money; synthetic data only.
- See `docs/TESTING.md` for failure cases.
