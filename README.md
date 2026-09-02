# PayTrust AI — Evidence-Driven Payment Safety & Authorization Layer

> **Razorpay Buildathon — AI-agent payment safety.** Controls whether an AI agent may spend on behalf of a user: **Policy → Risk → Evidence → AI Investigation (advisory) → Decision Simulation → ALLOW / ASK_USER / DENY → Razorpay TEST MODE**.

**Production-minded local prototype** — runs with **Streamlit + SQLite + Python 3.11/3.12**, no Docker/Postgres/Redis required for Phases 1-10. Deterministic policy is final; LLM never overrides.
![MIT](https://img.shields.io/badge/License-MIT-green) ![Python](https://img.shields.io/badge/Python-3.11%7C3.12-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.63-red) ![FastAPI](https://img.shields.io/badge/FastAPI-0.111-teal) ![scikit-learn](https://img.shields.io/badge/scikit--learn-1.5-orange) ![IEEE-CIS](https://img.shields.io/badge/dataset-IEEE--CIS%20590k-9cf) ![Tests](https://img.shields.io/badge/tests-128%20passed-brightgreen) ![CI](https://img.shields.io/github/actions/workflow/status/Sanskar1724/PayTrust_AI/ci.yml?branch=main)

## Brief → Product Mapping (read this first, judges)

The official brief (`../full_breif into.txt`) describes a *merchant payment-fraud risk platform*: payment events → risk → evidence → AI investigation → counterfactuals → **ALLOW / REVIEW / BLOCK** → human approval → audit. This product implements that exact pipeline, applied to the highest-stakes merchant-side abuse case: **an AI agent spending on a user's behalf**. Vocabulary and scope map as follows:

| Brief concept | This product | Where |
|---|---|---|
| Payment/order events → validation | Payment request (Pydantic) + Razorpay TEST MODE webhook events | `models/payment_request.py`, `services/razorpay_service.py` |
| Risk Intelligence (Rules + ML + behavior) | PolicyEngine (deterministic rules) + RiskEngine (7 behavioral dimensions) + IEEE-trained ML (threshold tool) | `engines/`, `models/` |
| Evidence Collection | Factors (name/severity/score/details), policy violations, customer/agent history — facts only | `engines/risk_engine.py` |
| AI Investigation (why suspicious?) | Advisory, fact-bound LLM explanation + concerns + review questions | `engines/ai_engine.py` |
| Counterfactual Engine (ALLOW/REVIEW/BLOCK expected costs) | DecisionSimulator: fraud exposure, FP cost, ops cost, friction, expected total cost per action | `engines/decision_simulator.py` |
| **ALLOW / REVIEW / BLOCK** | **ALLOW / ASK_USER / DENY** (ASK_USER ≡ REVIEW: human approval gate; DENY ≡ BLOCK) | `engines/decision_engine.py` |
| Best Expected Decision | Min expected-total-cost recommendation, subject to hard safety guards (policy violation → DENY; never auto-block on low confidence) | `engines/decision_simulator.py` |
| Human Approval | ASK_USER decision requires user approval before execution; audit-logged | `app.py`, `database/` |
| Audit + Analytics | `audit_logs` (who/what/when/request_id/decision/risk/latency), metrics, Dashboard | `core/logger.py`, `core/metrics.py` |
| Evaluation (precision/recall/F1/FPR/confusion, held-out) | Real IEEE-CIS temporal held-out test + reproducible harness | `evaluation/run_evaluation.py` |

**Deliberate deviations (documented, not hidden):** local prototype uses Streamlit + SQLite instead of React + Postgres/Redis (the production stack exists in `../ai-payment-copilot/`); the incident-cluster/verification engines are roadmap items (see `FINAL_STATUS.md` §8, §11); the synthetic generator (550 rows) is a smoke test — real-data evidence comes from IEEE-CIS 590k.

## 30-Second Demo


1. `streamlit run app.py` → Dashboard shows health, DB inspect, metrics.
2. **Agent Policy** → default policy: Test User + Shopping Assistant, daily 100k, max 60k, approval >30k, allowed `electronics,books,travel`, blocked `gambling,financial_products`.
3. **Payment Request** → create `req_...` amount 25k electronics → Policy `authorized True` → Risk `LOW 15` → Decision `ALLOW` → persisted + audit.
4. Change amount to 65k → `max_transaction_exceeded` → `DENY`; category gambling → `category_blocked` → `DENY`; amount 35k → `requires_approval` → `ASK_USER`.
5. **Risk Assessment** → slider to see 7 dimensions and factors.
6. **AI Investigation** → structured facts only → explanation (OpenRouter→Groq→Gemini→deterministic fallback).
7. **Decision Simulator** → `ALLOW` low friction vs `DENY` safe, all labeled `SIMULATED / ESTIMATED`, recommends min cost.
8. **Payment History** → filter, download CSV, generate `data/synthetic_transactions.csv` (seeded).
9. **Audit Log** → every decision with `request_id, event_type, decision, risk_score, processing_time` (no secrets).

## Architecture

See `docs/ARCHITECTURE.md:1` for diagram and module map. Key files:
Also see `docs/ROADMAP.md:1` — the 4-phase plan, buildathon-15 requirements checklist, and remaining optional items.

- `app.py:1` — Streamlit 10 pages
- `api/main.py:1` — FastAPI REST service over the tested engines (`docs/API.md`)
- `core/config.py:16` — env + validation
- `database/database.py:23` — SQLite WAL, 9 tables + `razorpay_events`
- `engines/policy_engine.py:61` / `engines/risk_engine.py:1` / `engines/decision_engine.py:1` / `engines/decision_simulator.py:1` / `engines/ai_engine.py:1`
- `services/razorpay_service.py:1` — HMAC raw body, idempotency
- `models/payment_request.py:1` — Pydantic validation
- `data/synthetic.py:1` → `data/synthetic_transactions.csv`

## Features

- **Deterministic PolicyEngine** — 10 cases tested (`tests/test_policy_engine.py:1`).
- **RiskEngine** — 7 dimensions → 0-100 + factors (`tests/test_risk_engine.py:1`).
- **DecisionEngine** — documented thresholds, no magic (`docs/DECISION_ENGINE.md`).
- **DecisionSimulator** — counterfactual `ALLOW/ASK/DENY` with `SIMULATED` costs (`engines/decision_simulator.py:1`).
- **AIEngine** — strict prompt, structured facts, fallback (`docs/AI_ENGINE.md`).
- **REST API** — `POST /v1/evaluate`, webhook, payments, evaluation metrics (`api/`, `docs/API.md`, 16 tests).
- **Synthetic Data** — seeded `500+50` rows, 6 scenarios (`data/synthetic.py:1`, `tests/test_synthetic.py:1`).
- **Razorpay Test Mode** — order create, webhook HMAC, idempotency (`services/razorpay_service.py:1`, `tests/test_razorpay.py:1`).
- **Security** — parameterized SQL, redacted logs, audit, checklist (`docs/SECURITY.md`).
- **Observability** — structured logs with `request_id`, metrics dashboard (`core/metrics.py:1`, `docs/OBSERVABILITY.md`).
- **Threshold Decision Tool** — real IEEE held-out test + SIMULATED cost model → merchant picks the operating point (precision/recall/FPR/cost trade-off, sweep curves, recommended points) via UI **and** REST (`models/threshold.py:1`, `api/routers/threshold.py:1`, `tests/test_threshold.py:1`).

## Setup

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env  # edit only if you need AI/Razorpay keys (TEST MODE only)
streamlit run app.py  # → http://localhost:8501
```

## Environment Variables

All via `core/config.py:16` and `.env.example`:

```
APP_NAME, APP_VERSION, ENVIRONMENT, SECRET_KEY
DATABASE_URL=sqlite:///./data/paytrust.db
RAZORPAY_KEY_ID=rzp_test_* (TEST ONLY)
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL
CB_FAILURE_THRESHOLD, CB_RECOVERY_TIMEOUT
RISK_THRESHOLD_LOW=30, RISK_THRESHOLD_MEDIUM=60, RISK_THRESHOLD_HIGH=80
FP_*, FN_*, WEBHOOK_*
```

Never commit `.env` (`.gitignore:1`).

## Running Locally

```powershell
python -m database.inspect
python -m database.inspect --json
python -m data.synthetic --normal 500 --anomalies 50 --seed 42  # → data/synthetic_transactions.csv
python -m models.ml_risk --train data/synthetic_transactions.csv --seed 42  # optional, → evaluation/ml_report.json
streamlit run app.py           # dashboard  → http://localhost:8501
python -m api.main             # REST API   → http://localhost:8000  | Swagger /docs
```

## API Service (FastAPI)

The tested engines are exposed as a real REST API (`api/`, `docs/API.md`):

```powershell
python -m api.main
```

- `POST /v1/evaluate` → `ALLOW / ASK_USER / DENY` with evidence + SIMULATED counterfactuals
  (auth: `X-API-Key`, default prints via `python -c "from api.security import api_key_for; print(api_key_for())"`).
- `POST /v1/webhooks/razorpay` → raw-body HMAC, idempotent.
- `GET /v1/payments`, `GET /v1/payments/{id}`, `GET /v1/evaluation/metrics`, `/health`, `/ready`.
- Deployment: `Dockerfile` + `docker-compose.yml` + `docs/DEPLOYMENT.md` (Hugging Face
  Spaces Docker recommended — free, serves both API + dashboard).
## External Resources & Integrations

| Resource | What it gives us | Status |
|---|---|---|
| [IEEE-CIS Fraud Detection (Kaggle](https://www.kaggle.com/datasets/mlg-ulb/ieee-fraud-detection) | Real 590k train + 506k test transactions; kept local ~1.3 GB (gitignored, never committed) | ✅ trained in chunks, 506,691 predictions |
| [Razorpay Payments API](https://razorpay.com/docs/api/payments/) | TEST-mode orders + webhooks (raw-body HMAC, idempotent, defense-only) | ✅ wired (`RAZORPAY_KEY_ID=rzp_test_*` in `.env`) |
| [Hugging Face Spaces (Docker](https://huggingface.co/new-space) | Free public URL serving dashboard + API behind one Space | 📋 `docs/DEPLOYMENT.md:1` |
| [OpenRouter](https://openrouter.ai/) / [Groq](https://groq.com/) / [Gemini](https://ai.google.dev/) / [Ollama](http://localhost:11434) | Advisory AI explanation (provider fallback chain → deterministic when offline) | 🔑 optional keys in `.env` |
| GitHub Actions | CI on push/PR: install → compile → 128 tests → threshold smoke | ✅ `.github/workflows/ci.yml` |
| Repo | [`github.com/Sanskar1724/PayTrust_AI`](https://github.com/Sanskar1724/PayTrust_AI) | 🔗 source |

**Safety:** Razorpay TEST MODE only, defense-only — no live money, no offensive features.

## Testing

```powershell
chcp 65001; $env:PYTHONUTF8="1"
python -m pytest tests/ -v --tb=short
# Expected: 115 tests, all pass (15 DB + 12 policy + 13 payment + 11 risk + 13 decision + 9 AI + 6 synthetic + 4 integration + 5 simulator + 6 razorpay + 5 security + 16 API)
```

See `docs/TESTING.md:1` for strategy and `docs/SECURITY.md:1` for checklist.

## Limitations (Honest)

- Local prototype — SQLite, no JWT/RBAC/rate limiting (stubs in `core/config.py`), no live Razorpay money, synthetic labels not real fraud.
- ML model trained on synthetic data only — see `evaluation/ml_report.json` disclaimer “not production performance”.
- LLM is advisory; deterministic engines are final.
- No Docker/Postgres/Redis in local track (preserved in `../ai-payment-copilot` for production).

## Future Improvements

- Postgres + Redis + FastAPI for `ai-payment-copilot` production track.
- Real IEEE-CIS dataset, calibrated probabilities, PR-AUC tuning.
- pgvector incident memory, Prometheus/Grafana, OpenTelemetry.
- RBAC, JWT refresh, idempotency keys for payment creation.

## Trust Story

AI Agent → Intent → Authorization → Policy → Risk → Evidence → AI Investigation → Decision Simulation → **ALLOW / ASK_USER / DENY** → Payment Infrastructure. Answers: is agent authorized? within policy? risky? why? what if allow/deny? should we ask user? can we safely execute?

## License

MIT — see `../ai-payment-copilot/README.md`
