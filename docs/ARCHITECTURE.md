# ARCHITECTURE.md — PayTrust AI

## Problem
AI agents can select products and initiate payments. Blindly trusting them to spend money is unsafe. We need a safety layer that answers: **Should this agent be allowed to make this payment on behalf of this user?**

## Solution
PayTrust AI is a **production-minded local prototype** (Streamlit + SQLite) that evaluates:

```
Agent Intent → Authorization → Policy → Risk → Evidence → AI Investigation (advisory) → Decision Simulation → ALLOW / ASK_USER / DENY → Payment (Razorpay TEST MODE)
```

Deterministic engines are final; LLM never overrides.

## High-Level Diagram

```
┌─────────────┐
│  AI Agent   │── Intent ──┐
└─────────────┘            ▼
                ┌─────────────────────┐
                │  PaymentRequest     │  models/payment_request.py:1 (Pydantic: request_id, user_id, agent_id, merchant_id, amount≥1, currency INR, category enum)
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  PolicyEngine       │  engines/policy_engine.py:61  deterministic
                │  daily 100k, max 60k, approval>30k, allowed [electronics,books,travel], blocked [gambling,financial_products]
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  RiskEngine         │  engines/risk_engine.py:1  7 dimensions → 0-100 + factors
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  DecisionEngine     │  engines/decision_engine.py:1  ALLOW / ASK_USER / DENY (no magic numbers)
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  DecisionSimulator  │  engines/decision_simulator.py:1  counterfactual ALLOW/ASK/DENY SIMULATED
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  AIEngine           │  engines/ai_engine.py:1  OpenRouter→Groq→Gemini→deterministic, strict prompt, advisory only
                └─────────┬───────────┘
                          ▼
                ┌─────────────────────┐
                │  Razorpay TEST MODE │  services/razorpay_service.py:1  HMAC raw body, idempotency, never live
                └─────────────────────┘
```

Persistence: SQLite `data/paytrust.db` with 9 tables (`database/database.py:23`): users, agents, agent_policies, merchants, payment_requests, risk_assessments, decisions, approvals, audit_logs + razorpay_events (Phase 11). All queries parameterized (`database/repositories.py:1`).

## Module Map

| Layer | Files | Responsibility |
|-------|-------|----------------|
| Core | `core/config.py:1`, `core/logger.py:1`, `core/exceptions.py:1`, `core/security.py:1`, `core/metrics.py:1` | Config (pydantic-settings), structured logging with redaction + request_id, typed errors, security checklist, metrics |
| Database | `database/database.py:1` (WAL, FK), `database/repositories.py:1`, `database/inspect.py:1` | Idempotent init, seed Test User/Shopping Assistant/4 merchants + default policy, inspection |
| Engines | `engines/policy_engine.py:61`, `engines/risk_engine.py:1`, `engines/decision_engine.py:1`, `engines/decision_simulator.py:1`, `engines/ai_engine.py:1` | Deterministic policy/risk/decision, counterfactual simulator, LLM abstraction |
| Models | `models/payment_request.py:1`, `models/ml_risk.py:1` | Pydantic validation, optional LogisticRegression on synthetic data |
| Services | `services/razorpay_service.py:1` | Razorpay Test Mode, webhook HMAC, idempotency |
| Data | `data/synthetic.py:1` → `data/synthetic_transactions.csv` | Seeded 500+50 rows, 6 scenarios, reproducible |
| UI | `app.py:1` (8 pages), `pages/` | Streamlit polished UI (metrics, cards, tables, charts, expanders) |
| Tests | `tests/test_*.py` (11 files, 80+ tests) | Unit + integration, mocked AI/weather, DB isolation via tmp files |
| Docs | `docs/*.md`, `README.md` | This doc + TESTING, SECURITY, DECISION_ENGINE, AI_ENGINE |

## Data Flow (Happy Path)

1. UI or API creates `PaymentRequest` → `repositories.create_payment_request` (parameterized, FK checks) → `audit_logs: PAYMENT_CREATED`.
2. `PolicyEngine.evaluate_request` queries `agent_policies` + `daily_spent` → `{authorized, requires_approval, violations}`.
3. `RiskEngine.assess_request` queries frequency + merchant/user history → `{risk_score, risk_level, factors}`.
4. `DecisionEngine.decide` → `ALLOW/ASK/DENY` with `reasons`; persists to `decisions` + `risk_assessments`.
5. `AIEngine.investigate(build_facts(...))` → explanation/concerns/review_qs (advisory, never changes decision).
6. `decision_simulator.simulate` → counterfactual table (SIMULATED).
7. If `ALLOW` and Razorpay enabled, `razorpay_service.create_test_order` (or SIMULATED); webhook via `handle_webhook` (HMAC raw body → idempotency → `razorpay_events`).

## Failure & Safety

- LLM unavailable → deterministic fallback (`engines/ai_engine.py:_deterministic_explanation`) keeps app usable.
- Webhook duplicate → `is_duplicate_event` idempotent ignore.
- Policy violation → hard `DENY` regardless of low risk.
- Secrets: only in `.env`, never in DB/UI/logs (`core/logger.py:18` redaction, `core/security.py:assert_no_secrets_in_db`).
- Circuit breaker: `AIEngine` tracks `CB_FAILURE_THRESHOLD` failures and opens.

## Scaling (Future, not in Phase 1)

Local SQLite can be swapped to Postgres via `DATABASE_URL` (already supported in `core/config.py:74`). Redis/Docker/K8s only if justified.

## File References

- Config: `core/config.py:16`
- DB schema: `database/database.py:23`
- Policy example: `engines/policy_engine.py:48`
- Risk thresholds: `core/config.py:56` and `engines/risk_engine.py:15`
- Decision boundaries: `engines/decision_engine.py:18`
- Simulator costs: `engines/decision_simulator.py:35`
- AI prompt: `engines/ai_engine.py:45`
