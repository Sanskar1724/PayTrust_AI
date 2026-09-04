# Software Requirements Specification (SRS) — PayTrust AI

> IEEE 830 / ISO 29148 style SRS for PayTrust AI v1.0
> Date: 2026-09-02

---

## 1. Introduction

### 1.1 Purpose
This SRS specifies the requirements for **PayTrust AI v1.0**, a payment-safety layer
that authorizes, asks human approval, or denies AI-agent-initiated payments based
on deterministic policy, ML risk scoring, advisory AI investigation, and a
counterfactual cost engine.

### 1.2 Scope
PayTrust AI is a defense-only software system. It:
- Receives a payment intent from an AI agent
- Evaluates the intent against merchant policy + risk + cost model
- Returns one of three decisions: **ALLOW / ASK_USER / DENY**
- Optionally invokes an LLM to generate a human-readable explanation (advisory only)
- Records the decision in an immutable audit trail
- Optionally forwards approved payments to Razorpay (Test Mode in v1.0)

It does NOT:
- Move money
- Store card numbers
- Perform offensive actions (no fraud investigation, no account takeover, no botnets)
- Make binding policy decisions from LLM output (LLM is advisory; deterministic engines are final)

### 1.3 Definitions, acronyms, abbreviations
See [`GLOSSARY.md`](GLOSSARY.md).

### 1.4 References
- Razorpay Buildathon Track 02 brief (`full_breif into.txt`, `prompt.txt`)
- IEEE Std 830-1998 (SRS format)
- ISO/IEC 25010 (software quality model)
- IEEE-CIS Fraud Detection dataset (Kaggle, 590k transactions)
### 2.1 System context

```
                    ┌──────────────────────┐
                    │   AI Agent (buyer)   │
                    │  OpenAI, Anthropic,  │
                    │  custom, etc.        │
                    └──────────┬───────────┘
                               │ POST /v1/evaluate
                               │ {amount, category, ...}
                               ▼
┌──────────────────────────────────────────────────────┐
│                    PayTrust AI                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Policy   │→ │  Risk    │→ │ Decision │→ Audit    │
│  │ Engine   │  │ Engine   │  │ Engine   │   Log     │
│  └──────────┘  └──────────┘  └──────────┘           │
│                       ↓                             │
│                ┌──────────────┐                     │
│                │ Counter-     │                     │
│                │ factual      │                     │
│                │ Simulator    │                     │
│                └──────────────┘                     │
│                       ↓ (advisory)                  │
│                ┌──────────────┐                     │
│                │  AI Engine   │→ LLM provider      │
│                │  (advisory)  │   chain             │


## 3. Product functions

(Full functional requirements with priority and acceptance criteria in [`FUNCTIONAL_REQ.md`](FUNCTIONAL_REQ.md).)

Top-level functions:
1. **Evaluate payment** — accept intent, return decision + evidence
2. **Manage agent policies** — CRUD for daily limit, max transaction, allowed/blocked categories
3. **Ingest Razorpay webhooks** — raw-body HMAC, idempotent, DLQ
4. **Generate AI explanation** — advisory, multi-provider fallback, deterministic last resort
5. **Compute counterfactuals** — simulate ALLOW/ASK_USER/DENY with SIMULATED costs
6. **Train and serve ML model** — chunked training on real fraud data
7. **Record audit log** — every decision, immutable, request_id-traceable
8. **Surface analytics** — KPIs, distributions, threshold curves

---

## 4. User characteristics

| Role | Technical level | Frequency of use | Primary interface |
|---|---|---|---|
| **Merchant ops** | Low–medium | Weekly (policy edits) | Streamlit dashboard |
| **Risk analyst** | Medium | Daily (review flagged) | Streamlit dashboard + REST API |
| **AI agent** | High | Per-payment | REST API |
| **End user** | Low | Per-ASK_USER (rare) | Mobile push / chat dialog |
| **Data scientist** | High | Quarterly (retrain) | CLI + Jupyter |
| **DevOps** | High | Continuous (ops) | kubectl, Grafana, PagerDuty |

---

## 5. Constraints

- **Regulatory:** Must support RBI Digital Lending Guidelines, EU AI Act, US state AI laws. Defense-only.
- **Security:** Razorpay Test Mode enforced in code (live keys refused). TLS 1.3 minimum. No card data stored.
- **Performance:** End-to-end P95 < 200ms (without LLM), < 2s (with LLM).
- **Availability:** 99.9% target.
- **Cost:** Variable cost per evaluation < ₹1 (Growth tier).
- **Portability:** Must run on Linux, macOS, Windows. Python 3.11–3.12.
- **Stack:** Python + FastAPI + Postgres + Redis + scikit-learn + Plotly (no proprietary deps).

---

## 6. Assumptions and dependencies

### 6.1 Assumptions
- Merchants have a verified Razorpay account (Test Mode in v1.0)
- The Razorpay webhook endpoint is publicly reachable
- End users have a way to receive ASK_USER prompts (mobile push, email, or chat)
- LLM provider availability is best-effort, not critical (deterministic fallback exists)
- The merchant is the data controller; we are the data processor

### 6.2 Dependencies
- Python 3.11 or 3.12
- Streamlit ≥ 1.63
- FastAPI ≥ 0.141
- scikit-learn ≥ 1.5
- Plotly ≥ 6.0
- PostgreSQL 16 (cloud only)
- Redis 7 (cloud only)
- Docker (cloud only)
- Razorpay API (optional, falls back to SIMULATED mode)

---

## 7. Specific requirements

### 7.1 Functional requirements
See [`FUNCTIONAL_REQ.md`](FUNCTIONAL_REQ.md) — 50+ detailed requirements,
MoSCoW-prioritized, with acceptance criteria.

### 7.2 Non-functional requirements
See [`NON_FUNCTIONAL_REQ.md`](NON_FUNCTIONAL_REQ.md) — performance, reliability,
security, scalability, observability, maintainability, portability, usability,
compliance, with measurable targets.

### 7.3 External interface requirements
See [`API_REFERENCE.md`](API_REFERENCE.md), [`INTEGRATIONS.md`](INTEGRATIONS.md).

### 7.4 Data requirements
See [`DATA_MODEL.md`](DATA_MODEL.md).

### 7.5 Design constraints
- All ML model artifacts in `models/` (gitignored for `.pkl`, `.joblib`)
- All audit-log writes are append-only
- No PII in error messages or logs (redaction enforced in `core/logger.py`)

### 7.6 Software system attributes
- **Maintainability:** Modular engines (`engines/`) + repositories (`database/`) + thin HTTP layer (`api/`)
- **Portability:** Same code runs on local + cloud via configuration
- **Reusability:** All engines are framework-agnostic; can be embedded in any Python app
- **Testability:** 128 tests cover engines, API, integrations

### 7.7 Other requirements
- **Localization:** English in v1.0; Hindi/Indonesian/Spanish planned
- **Accessibility:** WCAG 2.1 AA (dashboard)
- **Regulatory:** Defense-only; no offensive functionality; full audit trail

│                └──────────────┘                     │
└────────────────────────┬─────────────────────────────┘
                         │ ALLOW + payment intent
                         ▼
                  ┌──────────────┐
                  │   Razorpay   │
                  │  (PSP)       │
                  └──────────────┘
```

### 2.2 User interfaces
- **Streamlit dashboard** (11 sections: Dashboard, Agent Policy, Payment Request, Risk Assessment, AI Investigation, Decision Simulator, Payment History, Real World (IEEE), Evaluation & Thresholds, Help & Glossary, Audit Log)
- **REST API** (FastAPI, 11 routes, OpenAPI at /docs)
- **CLI** (`python -m evaluation.run_evaluation` for batch eval)

### 2.3 Hardware interfaces
None (cloud-software product).

### 2.4 Software interfaces
- Razorpay Orders API (`/v1/orders`)
- Razorpay Webhooks (`payment.captured`, `payment.failed`, `refund.processed`, etc.)
- OpenRouter / Groq / Gemini / Ollama (advisory LLM)
- IEEE-CIS Fraud Detection dataset (offline training only)
- Prometheus, Grafana, Sentry, OpenTelemetry (observability)
- Slack, PagerDuty (alerting)

### 2.5 Communication interfaces
- HTTPS REST (TLS 1.3)
- Webhook callbacks (HMAC-SHA256)
- WebSocket for live dashboard (Streamlit built-in)

### 2.6 Memory and storage constraints
- Local: SQLite database, 9 tables + `razorpay_events`
- Cloud: PostgreSQL 16, partitioned by month, ~50 GB/year at 1M tx/day
- Redis: idempotency keys + rate-limit counters, 1 GB sufficient
- Object storage: audit log archive (S3), 90 days hot + 7 years cold

---

- Razorpay Orders API, Webhooks spec

### 1.5 Overview
The rest of this document is organized as:
- §2 Product perspective
- §3 Product functions
- §4 User characteristics
- §5 Constraints
- §6 Assumptions and dependencies
- §7 Specific requirements (functional + non-functional)

---

## 2. Product perspective

PayTrust AI is a **standalone product** with three deployment shapes:

| Shape | Audience | Stack |
|---|---|---|
| **Local prototype** | Buildathon judge, demo, hackathon | Streamlit + SQLite + Python 3.12 |
| **Cloud SaaS** | Paying customers | FastAPI + Postgres + Redis + Kubernetes |
| **On-premise** | Banks, regulated industries | Docker Compose / Helm chart |

All three share the same Python core engines (`engines/`, `services/`, `models/`)
and differ only in the orchestration layer and storage backend.
