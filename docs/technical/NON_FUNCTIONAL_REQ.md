# Non-Functional Requirements — PayTrust AI

> NFR-1 … NFR-12, each with target, current status, and verification method.
> Status: ✅ met · 🟡 partially met (honest gaps documented) · 📋 planned (production).

## Performance

| ID | Requirement | Target | Status | Verify |
|---|---|---|---|---|
| NFR-1 | Decision latency | ≤ 50 ms p95 for policy+risk+simulate (no AI) | ✅ `processing_ms` ≈ 15 ms observed live | live `/v1/evaluate` response field `processing_ms` |
| NFR-2 | AI advisory latency | ≤ 12 s budget per provider call, non-blocking to decision | ✅ 12 s httpx timeout + circuit breaker + fallback chain | `engines/ai_engine.py:108` (`self.timeout = 12.0`) |
| NFR-3 | API throughput | ≥ 50 rps on 1 vCPU (dev hardware) | 🟡 untested under load; SQLite WAL handles it locally | load test planned (`locust`) |
| NFR-4 | Frontend first paint | Streamlit cold start ≤ 5 s, interaction ≤ 300 ms | ✅ verified locally (`/_stcore/health` `ok`, boot ≈ 9 s incl. process spawn) | live check 2026-09-02 |

## Reliability

| ID | Requirement | Target | Status | Verify |
|---|---|---|---|---|
| NFR-5 | Zero data loss on decisions | Every evaluation persisted before response returns | ✅ append-only `decisions` + `audit_logs` rows | `tests/test_database.py` |
| NFR-6 | Graceful degradation | App fully functional with all LLM providers down | ✅ deterministic fallback provider always available | `tests/test_ai_engine.py` (fallback chain tests) |
| NFR-7 | Webhook exactly-once semantics | Duplicate deliveries are idempotent-ignored | ✅ `razorpay_events.payload_hash` unique + `status=duplicate` | `tests/test_razorpay.py` |
| NFR-8 | Uptime | 99.5% monthly (production SLO) | 📋 planned — single-node dev today | DISASTER_RECOVERY.md |

## Security

| ID | Requirement | Target | Status | Verify |
|---|---|---|---|---|
| NFR-9 | Secrets hygiene | No secrets in code, DB, logs, or git | ✅ `.env` gitignored; `RedactingFormatter` scrubs `api_key`/`secret`/`sk-or-v1-`/`rzp_test_`/`gsk_`; `assert_no_secrets_in_db` test | `tests/test_security.py`, `core/logger.py:18` |
| NFR-10 | Auth on all sensitive endpoints | 401 without valid `X-API-Key`; webhook HMAC mandatory | ✅ enforced via `api_key_dependency` + raw-body HMAC verify | live check (401 observed), `tests/test_api.py` |

## Scalability & Maintainability

| ID | Requirement | Target | Status | Verify |
|---|---|---|---|---|
| NFR-11 | Horizontal scalability path | Stateless API nodes + swap SQLite→Postgres via `DATABASE_URL` | 🟡 repositories abstract DB access; async engines stateless; Redis/K8s planned | `core/config.py:36`, `database/repositories.py` |
| NFR-12 | Observability | Structured JSON logs, health/readiness probes, per-request trace id | ✅ structlog JSON + `/health` + `/ready` + `request_id` on every record | `core/logger.py`, live `/ready` response |

## Constraint register (honest limitations)

- **Single-node SQLite** in dev: fine to ~10k tx/day; production path documented in SCALABILITY.md.
- **Rate limiting** configured (`RATE_LIMIT_REQUESTS=100/60s`) but enforced per-process only — needs Redis token bucket in multi-node production.
- **IEEE-CIS model** is trained offline (Logistic + IsolationForest, PR-AUC 0.314 held-out); no online learning — model refresh is a documented ops task.
- **Cost model** figures are SIMULATED/ESTIMATED by design and labeled as such everywhere they appear.
