# Architecture — PayTrust AI

> Detailed system architecture: layers, components, data flow, deployment.

---

## 1. Architectural style

PayTrust AI follows a **layered, event-driven, polyglot-persistence** architecture:

- **Layered** — clear separation: presentation → orchestration → engines → persistence
- **Event-driven** — webhook ingestion is async via a queue (in production)
- **Polyglot persistence** — Postgres for transactions, Redis for ephemeral state, S3 for cold audit

The system is **defense-only**, **deterministic-final** (LLM is advisory), and
**evidence-driven** (every decision has auditable factors).

---

## 2. Logical architecture

```
┌──────────────────────────────────────────────────────────────┐
│ PRESENTATION                                                 │
│  Streamlit dashboard (11 pages)  │  REST API (11 routes)    │
│  app.py                          │  api/main.py             │
└──────────────┬───────────────────┴──────────────┬───────────┘
               │                                  │
               ▼                                  ▼
┌──────────────────────────────────────────────────────────────┐
│ ORCHESTRATION                                                │
│  FastAPI request handlers  │  Background worker (webhook)    │
│  api/routers/*.py          │  app/worker/main.py            │
└──────────────┬──────────────────────────────┬────────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│ ENGINES (pure-Python, framework-agnostic)                    │
│  PolicyEngine  → RiskEngine → DecisionEngine                 │
│  DecisionSimulator (counterfactuals)                         │
│  AIEngine (advisory, multi-provider fallback)                │
│  engines/*.py                                                 │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│ PERSISTENCE                                                  │
│  Repositories (DB-agnostic)  │  Services (Razorpay, LLMs)   │
│  database/repositories.py    │  services/*.py               │
│  SQLAlchemy 2.0 async / aiosqlite                            │
└──────────────┬──────────────────────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
---

## 3. Request flow: AI agent evaluates a payment

```
Step 1: Agent → POST /v1/evaluate {amount, category, user_id, agent_id, ...}
  Headers: X-API-Key, X-Request-ID

Step 2: API service validates (Pydantic), loads agent policy from DB

Step 3: PolicyEngine.evaluate(policy, payment, daily_spent) →
  {authorized: bool, requires_approval: bool, violations: [...]}

Step 4: RiskEngine.assess(payment, policy_result, context) →
  {risk_score: 0-100, risk_level: LOW|MEDIUM|HIGH|CRITICAL, factors: [...]}

Step 5: DecisionEngine.decide(policy_result, risk_result) →
  {decision: ALLOW|ASK_USER|DENY, reasons: [...]}

Step 6: DecisionSimulator.simulate(payment, policy, risk, decision) →
  {counterfactuals: [...], recommended: ALLOW|ASK_USER|DENY, reason: ...}

Step 7 (optional, if investigate=true): AIEngine.investigate(facts) →
  {explanation, summary, concerns, review_questions, confidence}

Step 8: Persist payment_request + audit_log row(s)

Step 9: Return JSON response {decision, risk, factors, counterfactuals, ai?, request_id}
```

End-to-end P50 < 50ms, P95 < 200ms (no LLM call); +1-2s with LLM.

---

## 4. Webhook flow (Razorpay → PayTrust AI)

```
Razorpay                 PayTrust AI                  Postgres + Redis
   │                          │                             │
   │  POST /v1/webhooks/      │                             │
   │  razorpay (raw body)     │                             │
   ├─────────────────────────▶│                             │
   │                          │ 1. verify HMAC-SHA256        │
   │                          │    (constant-time compare)  │
   │                          │                             │
   │                          │ 2. compute payload_hash     │
   │                          │ 3. is_duplicate_event?      │
   │                          │── Redis GET idempotency ──▶│
   │                          │◀── HIT / MISS ─────────────│
   │                          │                             │
---

## 5. ML pipeline

```
IEEE-CIS dataset (590k train, 506k test)         Ground truth
        │                                              │
        ▼                                              │
[Chunked training — 14,450 rows after sampling]        │
  models/train_ieee_chunked.py                        │
        │                                              │
        ▼                                              │
Logistic regression (scikit-learn)                    │
  models/ieee_model.pkl                               │
        │                                              │
        ▼                                              │
[Predict on held-out test 3,000 rows]                │
  models/predict_ieee.py                              │
        │                                              │
        ▼                                              ▼
evaluation/ieee_test_predictions.parquet  →  metrics (PR-AUC, ROC-AUC, F1, confusion)
```

### 5.1 Why chunked training?

The IEEE dataset is 1.3 GB. Loading it all into memory on a free-tier VM
(Hugging Face Spaces, Railway) is infeasible. `models/train_ieee_chunked.py`
streams the CSV in 50k-row chunks, samples, trains incrementally, and never
holds the full dataset in RAM.

### 5.2 Why held-out temporal split?

Random K-fold would over-estimate performance (the model could memorize nearby
time-correlated fraud patterns). A temporal split — train on the first 85% of
rows, test on the last 15% — is the honest evaluation for fraud detection.

### 5.3 Feature engineering (90+ features)

- Numerical: `TransactionAmt`, `card1-6`, `addr1-2`, `dist1-2`
- Time: `hour`, `day`, `is_night`, `is_weekend`
- Aggregations: `card1_count` (velocity), `amt_per_card_mean`
- Identity: `has_identity` (DeviceInfo present?)
- Encodings: ProductCD, card4 (network), card6 (debit/credit), P_emaildomain, DeviceType
- Missing-as-signal: `V_missing`, `DeviceType_Missing` etc.
---

## 7. State management

### 7.1 In-process state
- **Streamlit session state** — UI ephemeral state (sliders, form values)
- **Python module-level** — AIEngine providers, policy engine instance
- **No in-memory business data** — everything persisted to DB

### 7.2 Database state
- **9 tables** in Postgres / SQLite — see [`DATA_MODEL.md`](DATA_MODEL.md)
- **Append-only audit_logs** — no UPDATE or DELETE allowed
- **Soft deletes** for user/agent/merchant — preserve audit trail

### 7.3 Caching
- `@st.cache_resource` for AIEngine (don't reinit provider chain per request)
- `@st.cache_data(ttl="5m")` for expensive lookups (e.g., threshold curves)
- Redis (production) for cross-instance caching

---

## 8. Failure modes & recovery

| Failure | Detection | Recovery |
|---|---|---|
| LLM provider down | Provider returns 5xx or timeout | Circuit breaker → next provider → deterministic fallback |
| Postgres down | Connection error on read/write | Retry 3x with backoff; degrade to read-only mode |
| Redis down | Connection refused | Skip idempotency cache; rely on DB unique constraint (still correct, just slower) |
| Razorpay webhook 5xx | Razorpay retries automatically; we return 200 with queued event | Worker processes event when service recovers |
| Worker process crash | PM2 / k8s auto-restart | In-flight events picked up from queue on restart |
| Disk full | Database write fails | Alert; new requests rejected; old data unaffected |
| ML model missing | `FileNotFoundError` at load | Heuristic-only mode (deterministic policy + rules); merchant notified |
| Rzp secret missing | `verify_webhook_signature` returns True (warning logged) | All events processed without HMAC — DANGEROUS, alerts fire |

---

## 9. Security architecture

- **Defense in depth:** network (TLS), application (auth, RBAC, rate-limit), data (encryption), audit (logs)
- **HMAC over RAW body** for webhooks (signature BEFORE JSON parse, prevents parameter injection)
- **Constant-time compare** (`hmac.compare_digest`) to prevent timing attacks
- **Live-key refusal:** code refuses `RAZORPAY_KEY_ID` not starting with `rzp_test_`
- **Secret redaction** in logs (`core/logger.py` filters tokens, keys, PII)
- **No card data stored** — only order_id, payment_id, amount, status
- **Row-level security** (RLS) in Postgres — merchants see only their own data
- **No SQL string interpolation** — all queries parameterized via SQLAlchemy

See [`SECURITY.md`](SECURITY.md) for the full threat model.

---

## 10. Observability

- **Logs:** structured JSON, `request_id` propagation, redacted, shipped to Loki (prod) or stdout (dev)
- **Metrics:** Prometheus, custom counters (`total_requests`, `by_decision`, `policy_violations`, `ai_failures`)
- **Traces:** OpenTelemetry (planned; manual `request_id` today)
- **Health endpoints:** `/health` (liveness), `/ready` (readiness — checks DB + Redis)
- **Audit log UI:** in-app "Audit Log" page lists last 50 decisions

See [`../OBSERVABILITY.md`](../OBSERVABILITY.md).

---

## 11. Deployment architectures

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full breakdown of:
- Local development (Streamlit + SQLite)
- Hugging Face Spaces (Docker, free tier)
- AWS ECS Fargate (small scale)
- Kubernetes (production)

---

## 12. Future architecture

Items deliberately not in v1.0 (planned for v1.1–v2.0):
- **Multi-tenant data plane** with strict row-level isolation
- **Streaming risk events** via Kafka / Kinesis (currently batch via DB polling)
- **Online learning** — model auto-updates from new audit-log decisions
- **pgvector** for similarity search on historical fraud patterns
- **Vector embeddings** of `agent_reason` for richer features
- **Real-time webhook subscriptions** (WebSocket out from PayTrust to merchant)
- **Mobile SDKs** (iOS, Android) for ASK_USER push notifications

- C/D/M: counting, delta-time, matching features (anonymized)

---

## 6. Counterfactual engine design

The counterfactual engine is the **primary differentiator**. It answers:
> "If we ALLOW this payment, what's the expected cost? ASK_USER? DENY?"

For each action, the engine computes:
- **fraud_exposure** = `p_fraud × amount × FN_FRAUD_EXPOSURE_MULTIPLIER`
  (where `p_fraud = min(1, risk_score/100)`)
- **false_positive_cost** = `FP_CUSTOMER_FRICTION_COST + FP_SUPPORT_COST + FP_MERCHANT_IMPACT_COST + amount × FP_LOST_TRANSACTION_VALUE_MULTIPLIER × 0.1`
- **operational_cost** = `{ALLOW: 0, ASK_USER: 250, DENY: 120}` INR
- **customer_friction** = `{ALLOW: low, ASK_USER: medium, DENY: high}`
- **expected_total_cost** = sum of the above, minus `0.95 × fraud_exposure` for blocked-when-fraud

**Hard policy guard:** if the payment violates policy (e.g., `category_blocked`),
the ALLOW counterfactual is suppressed — even if it would be cheaper — because
policy is law, not optimization.

   │                          │ 4. INSERT INTO              │
   │                          │    razorpay_events          │
   │                          │── INSERT ─────────────────▶│
   │                          │                             │
   │                          │ 5. enqueue for processing   │
   │                          │ 6. return 200 OK           │
   │  200 OK                  │                             │
   │◀─────────────────────────│                             │
   │                          │                             │
   │                          │  (async worker)             │
   │                          │  7. process event           │
   │                          │  8. update risk / policy    │
   │                          │  9. mark_event_processed   │
   │                          │── UPDATE ─────────────────▶│
```

### 4.1 Idempotency

- Key: `event_id` (Razorpay-provided) + `payload_hash` (sha256 of body)
- Stored in `razorpay_events` table + Redis cache (24h TTL)
- Duplicate event: return 200 OK, do not re-process
- Different payload hash with same event_id: log warning, treat as duplicate (safety > correctness)

### 4.2 Retry & DLQ

- Failed processing → exponential backoff (1s, 5s, 30s) → max 3 retries
- After 3 failures → DLQ table (manual replay)
- All retries logged with attempt number, error message

┌──────────────┐  ┌──────────────┐
│ POSTGRES 16  │  │   REDIS 7    │
│ 9 tables     │  │ idempotency, │
│ + razorpay_  │  │ rate-limit   │
│   events     │  │              │
└──────────────┘  └──────────────┘
```

### 2.1 Layer responsibilities

**Presentation layer** — no business logic. Just rendering and input validation.
- `app.py` (Streamlit)
- `api/main.py` (FastAPI)
- `api/routers/*.py` (HTTP endpoints)

**Orchestration layer** — wires the engines together, manages request lifecycle.
- `api/service.py` (the `/v1/evaluate` flow)
- `app/worker/main.py` (background webhook processor, production only)

**Engines layer** — pure functions of `(state, request) → decision`. No I/O.
- `engines/policy_engine.py` (61 lines, 10 test cases)
- `engines/risk_engine.py` (7 dimensions)
- `engines/decision_engine.py` (ALLOW/ASK_USER/DENY)
- `engines/decision_simulator.py` (counterfactuals)
- `engines/ai_engine.py` (advisory, OpenRouter→Groq→Gemini→deterministic)

**Persistence layer** — abstracts DB access behind repository pattern.
- `database/repositories.py` (CRUD)
- `database/database.py` (engine, init, seed)
- `services/razorpay_service.py` (external API client)
