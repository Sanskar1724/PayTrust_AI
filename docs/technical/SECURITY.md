# Security — PayTrust AI

> Threat model, controls, and evidence. Principle: **defense-only** — PayTrust
> authorizes, asks, or denies; it never performs offensive actions.

## Threat model (STRIDE summary)

| Threat | Vector | Control | Evidence |
|---|---|---|---|
| Spoofing | Fake agent calls API | `X-API-Key` on every `/v1/*` route | live 401 observed; `tests/test_api.py` |
| Spoofing | Forged Razorpay webhook | HMAC-SHA256 over RAW body vs `RAZORPAY_WEBHOOK_SECRET` | `tests/test_razorpay.py` |
| Tampering | Modified decision records | Append-only `decisions`/`audit_logs`; no update/delete paths in repositories | `database/repositories.py` |
| Repudiation | "We never denied that" | `request_id`-keyed immutable audit trail with full evidence JSON | `audit_logs` table |
| Information disclosure | Secrets in logs/DB/git | `RedactingFormatter` scrubs `api_key`, `secret`, `sk-or-v1-`, `rzp_test_`, `gsk_`; `assert_no_secrets_in_db` scans schema; `.env` gitignored | `core/logger.py:18`, `tests/test_security.py` |
| Denial of service | Request floods | `RATE_LIMIT_REQUESTS=100 / RATE_LIMIT_WINDOW=60s` (per-process; Redis needed for multi-node) | `core/config.py:60` |
| Elevation of privilege | LLM overrides policy | Impossible by design — LLM is advisory-only; decision engine is deterministic | `engines/decision_engine.py`, disclaimer on every response |
| Injection | Malformed payloads | Pydantic validation → structured 422; SQL via parameterized repositories | live 422 observed |

## Authentication & authorization

- **API keys** for service-to-service (`/v1/*`); dev key derived from `SECRET_KEY`,
  production sets `PAYTRUST_API_KEY` explicitly.
- **Razorpay Test-Mode enforcement**: `RAZORPAY_KEY_ID` must start `rzp_test_`;
  live keys are refused (guard in `services/razorpay_service.py`).
- **Agent authorization**: an agent can only spend within its `agent_policies`
  row — daily limit, max transaction, approval threshold, category/merchant
  allow+block lists (PolicyEngine).
- **Human approval** gates: amounts > `approval_threshold` → ASK_USER, recorded in
  `approvals` with approver identity.

## Data protection

- **No PII to LLMs**: AI providers receive structured facts only — amounts,
  categories, violation codes, factor names. No names, emails, or free-text
  account data leave the process (`engines/ai_engine.py:build_facts`).
- **Secrets handling**: only `.env` (gitignored); `.env.example` is the template;
  logs redact; DB columns scanned for secret-like names in tests.
- **Audit trail**: every decision event (creation, policy edit, approval, webhook)
  lands in `audit_logs` with actor + metadata — exportable for compliance.

## Residual risks (honest)

- Per-process rate limiting only → add Redis token bucket before multi-node prod.
- HS256 symmetric JWT config present (`SECRET_KEY`, `ALGORITHM`) but user-facing
  JWT auth is not the primary flow yet — API keys are.
- No WAF/TLS termination in dev — terminate TLS at the reverse proxy in production.
