# Functional Requirements — PayTrust AI v1.0

> 55 detailed functional requirements. MoSCoW-prioritized (Must / Should / Could / Won't).
> Each FR has a unique ID, description, acceptance criteria, and verification method.

---

## Conventions

- **MUST** = required for v1.0
- **SHOULD** = planned for v1.0, may slip to v1.1
- **COULD** = nice-to-have, defer
- **WON'T** = explicitly out of scope


## FR-1: Payment evaluation

### FR-1.1 [MUST] Evaluate payment intent
**Description:** System MUST accept a payment intent from an agent and return a decision (ALLOW/ASK_USER/DENY) with evidence.
**Acceptance:**
- Given a valid `PaymentRequest` payload
- When the agent calls `POST /v1/evaluate`
- Then system returns `200 OK` with `{decision, risk_score, risk_level, factors, counterfactuals, request_id}`
- And the response time is P95 < 200ms (no LLM) or < 2s (with LLM)
- And the decision is persisted with `request_id` for audit
**Verify:** `tests/test_api.py::test_evaluate_returns_decision`

### FR-1.2 [MUST] Reject malformed payment
**Given:** invalid Pydantic input (negative amount, missing field)
**When:** `POST /v1/evaluate` called
**Then:** 422 with structured error response, no DB write
**Verify:** `tests/test_payment_validation.py`

### FR-1.3 [MUST] Reject unauthenticated request
**Given:** missing or invalid `X-API-Key`
**When:** `POST /v1/evaluate` called
**Then:** 401 Unauthorized
**Verify:** `tests/test_api.py::test_evaluate_requires_api_key`

### FR-1.4 [MUST] Idempotent on `request_id`
**Given:** the same `request_id` sent twice
**When:** the second call arrives
**Then:** return the cached decision (no double-processing, no double-charge)
**Verify:** `tests/test_api.py::test_idempotency`

### FR-1.5 [SHOULD] Optional AI investigation
**Given:** `investigate=true` in payload
**When:** evaluating
**Then:** include `ai` object in response with `explanation`, `concerns`, `review_questions`, `confidence`
**Verify:** `tests/test_api.py::test_evaluate_with_ai_investigation_deterministic`

---

## FR-2: Policy engine

### FR-2.1 [MUST] Enforce daily limit
**Given:** policy.daily_limit=100k, daily_spent=80k, payment=30k
**When:** evaluated
**Then:** `violations=[daily_limit_exceeded]`, decision=ASK_USER or DENY
**Verify:** `tests/test_policy_engine.py`

### FR-2.2 [MUST] Enforce max transaction
**Given:** policy.max_transaction=60k, payment=65k
**Then:** `violations=[max_transaction_exceeded]`, decision=DENY
**Verify:** `tests/test_policy_engine.py`

### FR-2.3 [MUST] Enforce approval threshold
**Given:** policy.approval_threshold=30k, payment=35k, no other violations
**Then:** `requires_approval=True`, decision=ASK_USER
**Verify:** `tests/test_policy_engine.py`

### FR-2.4 [MUST] Enforce allowed categories
**Given:** allowed=[electronics, books], payment.category=gambling
**Then:** `violations=[category_blocked]`, decision=DENY
**Verify:** `tests/test_policy_engine.py`

### FR-2.5 [MUST] CRUD agent policy via dashboard
**Verify:** Streamlit "Agent Policy" page persists changes; audit log entry created
**Verify:** `tests/test_integration.py::test_policy_crud`

### FR-2.6 [SHOULD] Multi-policy support (per merchant / per region)
**Verify:** policy can be filtered by `merchant_id` and `region` fields

---

## FR-3: Risk engine

### FR-3.1 [MUST] Compute 0-100 risk score
**Verify:** `tests/test_risk_engine.py` — 7 dimensions, weighted sum capped at 100
**Acceptance:** Given any input, output is integer in [0, 100]

### FR-3.2 [MUST] Map score to level
**Acceptance:**
- score < 31 → LOW (green)
- 31 ≤ score < 61 → MEDIUM (yellow)
- 61 ≤ score < 81 → HIGH (orange)
- score ≥ 81 → CRITICAL (red)
**Verify:** `tests/test_risk_engine.py::test_levels`

### FR-3.3 [MUST] Return factors with severity
**Acceptance:** every factor has `{name, severity: low/medium/high, score: 0-25, details: str}`
**Verify:** `tests/test_risk_engine.py`

### FR-3.4 [MUST] 7 documented dimensions
- amount
- daily_spent
- transaction velocity (tx/hour)
- new device
- category risk
- merchant risk
- policy violations (hard guard)
**Verify:** `engines/risk_engine.py:1-50` (docstring) + tests

### FR-3.5 [SHOULD] ML probability as factor
**Given:** ML model loaded, IEEE-like features provided
**When:** evaluating
**Then:** `factors` includes `ml_ieee` with prob and severity
**Verify:** Streamlit "Real World (IEEE)" page


## FR-6: AI investigation engine

### FR-6.1 [MUST] Multi-provider fallback chain
**Acceptance:** OpenRouter → Groq → Gemini → deterministic fallback
**Verify:** `tests/test_ai_engine.py`

### FR-6.2 [MUST] Circuit breaker per provider
**Acceptance:** After N consecutive failures, provider skipped for cooldown
**Verify:** `engines/ai_engine.py::ProviderState`

### FR-6.3 [MUST] Fact-bound prompt
**Acceptance:** LLM receives ONLY structured facts; cannot invent amounts/merchants/scores
**Verify:** `engines/ai_engine.py::STRICT_PROMPT_TEMPLATE`

### FR-6.4 [MUST] Deterministic fallback
**Acceptance:** All providers fail → template explanation based on factors
**Verify:** `tests/test_ai_engine.py::test_deterministic_fallback`

### FR-6.5 [MUST] Never override deterministic decision
**Acceptance:** AI is advisory; decision comes from DecisionEngine
**Verify:** `tests/test_api.py::test_evaluate_with_ai_investigation_deterministic`

### FR-6.6 [SHOULD] Track latency, tokens, fallback usage
**Verify:** `ai_res` includes `latency_ms`, `tokens`, `fallback_used`, `provider`, `model`

### FR-6.7 [COULD] Streaming explanation (SSE)

---

## FR-7: Razorpay integration

### FR-7.1 [MUST] Verify webhook HMAC-SHA256 over RAW body
**Verify:** `tests/test_razorpay.py::test_verify_signature_correct`

### FR-7.2 [MUST] Idempotent event processing
**Verify:** `tests/test_razorpay.py::test_idempotency_duplicate`

### FR-7.3 [MUST] Refuse non-Test-Mode keys
**Verify:** `services/razorpay_service.py:39-41`

### FR-7.4 [MUST] Retry with exponential backoff + DLQ
**Verify:** `services/razorpay_service.py`

### FR-7.5 [SHOULD] Create Razorpay orders via API
**Verify:** `services/razorpay_service.py::create_order`

### FR-7.6 [COULD] Handle refund webhooks

---

## FR-8: Audit trail

### FR-8.1 [MUST] Every decision logged
**Verify:** `tests/test_integration.py::test_audit_log_created`

### FR-8.2 [MUST] Immutable audit log (append-only)
**Verify:** `database/repositories.py` — no update/delete for audit_logs

### FR-8.3 [MUST] Request-ID traceability
**Verify:** `tests/test_api.py::test_request_id_header_echoed`

### FR-8.4 [SHOULD] Queryable by time range, actor, decision

### FR-8.5 [COULD] Export to CSV / S3

---

## FR-9: ML evaluation

### FR-9.1 [MUST] Reproducible evaluation command
**Verify:** `python evaluation/run_evaluation.py`

### FR-9.2 [MUST] Compute precision, recall, F1, FPR, FNR, confusion, PR-AUC, ROC-AUC
**Verify:** `evaluation/run_evaluation.py`

### FR-9.3 [MUST] Threshold sweep with SIMULATED cost model
**Verify:** `evaluation/results.json::threshold_sweep`

### FR-9.4 [MUST] Honest disclaimer on all numbers
**Verify:** `evaluation/run_evaluation.py::DISCLAIMER`

### FR-9.5 [SHOULD] Merge synthetic demo model report

---

## FR-10: Dashboard (Streamlit)

### FR-10.1 [MUST] 11 pages with sidebar navigation
### FR-10.2 [MUST] Real-time decision on Payment Request page
### FR-10.3 [MUST] Interactive Risk Assessment with gauge
### FR-10.4 [MUST] AI Investigation with provider info
### FR-10.5 [MUST] Evaluation page with threshold slider + curves
### FR-10.6 [SHOULD] Dark theme
### FR-10.7 [COULD] Real-time audit log streaming

---

## FR-11: REST API (FastAPI)

### FR-11.1 [MUST] 11 routes
### FR-11.2 [MUST] OpenAPI docs at /docs
### FR-11.3 [MUST] API key auth on all /v1 routes
### FR-11.4 [MUST] Request-ID header echoed
### FR-11.5 [SHOULD] Rate limiting (100 req/min per API key)

---

## Coverage summary

| Category | MUST | SHOULD | COULD |
|---|---|---|---|
| Payment evaluation | 5 | 1 | 0 |
| Policy engine | 5 | 1 | 0 |
| Risk engine | 4 | 2 | 0 |
| Decision engine | 4 | 0 | 0 |
| Counterfactuals | 3 | 2 | 0 |
| AI investigation | 5 | 1 | 1 |
| Razorpay | 4 | 1 | 1 |
| Audit trail | 3 | 1 | 1 |
| ML evaluation | 4 | 1 | 0 |
| Dashboard | 5 | 1 | 1 |
| REST API | 4 | 1 | 0 |
| **Total** | **46** | **12** | **5** |

All 46 MUST requirements are implemented and tested.

### FR-3.6 [SHOULD] Daily spend computed from DB
**Verify:** `database/repositories.py` queries last 24h of payment_requests for the user

---

## FR-4: Decision engine

### FR-4.1 [MUST] DENY on policy violation
**Acceptance:** If any violation, decision=DENY (no LLM can override)
**Verify:** `tests/test_decision_engine.py`

### FR-4.2 [MUST] ASK_USER on approval requirement
**Acceptance:** If `requires_approval=True` (and no violations), decision=ASK_USER
**Verify:** `tests/test_decision_engine.py`

### FR-4.3 [MUST] Map risk to decision
**Acceptance:**
- risk_level=CRITICAL → DENY
- risk_level=HIGH → ASK_USER
- risk_level=MEDIUM → ASK_USER (configurable)
- risk_level=LOW → ALLOW
**Verify:** `tests/test_decision_engine.py`

### FR-4.4 [MUST] Deterministic — same input = same output
**Verify:** repeated calls with same state return same decision
**Verify:** `tests/test_decision_engine.py`

---

## FR-5: Counterfactual simulator

### FR-5.1 [MUST] Compute ALLOW/ASK_USER/DENY counterfactuals
**Acceptance:** Returns array of 3 objects with `{action, fraud_exposure, false_positive_cost, operational_cost, customer_friction, expected_total_cost, policy_violation, rationale}`
**Verify:** `tests/test_simulator.py`

### FR-5.2 [MUST] Recommended = min expected cost subject to hard guards
**Acceptance:** If ALLOW has policy_violation=true, it cannot be recommended even if cheaper
**Verify:** `tests/test_simulator.py::test_recommendation_respects_policy`

### FR-5.3 [MUST] Label all costs as SIMULATED / ESTIMATED
**Verify:** Every counterfactual object has `label: "SIMULATED / ESTIMATED"` field

### FR-5.4 [SHOULD] Cost model from config
**Verify:** Changing `FP_*` or `FN_*` in `.env` changes outputs (without code change)

### FR-5.5 [SHOULD] Real amounts in counterfactuals
**Acceptance:** `fraud_exposure = amount × p_fraud × multiplier` (not constant)

---


Acceptance criteria use **Given/When/Then** style.

---
