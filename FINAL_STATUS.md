# FINAL_STATUS.md — PayTrust AI

**Track:** Razorpay Buildathon — Track 02, AI Risk Manager
**Product:** PayTrust AI — Evidence-Driven Payment Risk & Loss Prevention (AI-agent spending safety layer)
**Status:** ✅ Core product complete — working, tested (128 passed), measured on real data
**Repo:** `github.com/Sanskar1724/PayTrust_AI` · local prototype: `paytrust-ai/` · production-stack prototype: `ai-payment-copilot/`
**All numbers below are generated from actual runs** (`python evaluation/run_evaluation.py`, `pytest`) — none are fabricated.

---

## 1. Project status

| Area | Status |
|---|---|
| Working product (Streamlit 11-section dashboard + FastAPI REST) | ✅ boots, `200 ok` |
| Deterministic engines (Policy → Risk → Decision → Counterfactual Simulator) | ✅ |
| AI investigation (advisory, provider fallback + circuit breaker) | ✅ works offline (deterministic fallback) |
| ML on real data (IEEE-CIS, chunked training, temporal held-out) | ✅ trained, evaluated, committed predictions |
| Razorpay TEST MODE (orders, webhooks, HMAC, idempotency, DLQ) | ✅ |
| Tests | ✅ **128 passed** (`python -m pytest tests/ -q`, 2026-09-02) |
| CI (GitHub Actions: install → compile → tests → smoke) | ✅ `.github/workflows/ci.yml` |
| Reproducible evaluation (`python evaluation/run_evaluation.py` → `results.json` + `report.md`) | ✅ |
| Deployment | 📋 Optional — `docs/DEPLOYMENT.md` (Hugging Face Spaces Docker) |

## 2. Architecture (one line per stage)

```
AI Agent intent → PolicyEngine (deterministic authorization)
                → RiskEngine (7 dimensions → 0-100 + factors)
                → Evidence (factors, violations, history — facts only)
                → AIEngine (advisory explanation; OpenRouter→Groq→Gemini→deterministic)
                → DecisionSimulator (counterfactual ALLOW/ASK_USER/DENY + SIMULATED costs)
                → DecisionEngine (ALLOW / ASK_USER / DENY)
                → Razorpay TEST MODE (bounded, simulated execution)
                → Audit log + metrics (request_id, decision, risk, latency — no secrets)
```

LLM is **advisory only** and never overrides deterministic policy. All counterfactual costs are labeled `SIMULATED / ESTIMATED`.

## 3. Implemented features (files)

- `engines/policy_engine.py` — daily limit, max transaction, approval threshold, allow/block categories
- `engines/risk_engine.py` — 7 transparent dimensions → 0–100 + severity-ranked factors
- `engines/decision_engine.py` — documented thresholds (`docs/DECISION_ENGINE.md`)
- `engines/decision_simulator.py` — counterfactuals: fraud exposure, FP cost, operational cost, friction, expected total cost; min-cost recommendation subject to hard policy guards
- `engines/ai_engine.py` — fact-bound strict prompt, provider chain + circuit breaker + 429 fallback models
- `models/train_ieee_chunked.py` / `models/predict_ieee.py` — chunked training on 590k real transactions, 506,691 test predictions
- `models/ml_risk.py` — synthetic demo model (logistic + Isolation Forest), explicitly disclaimed
- `services/razorpay_service.py` — raw-body HMAC-SHA256, idempotent events, retry/backoff, DLQ; hard-fails on non-`rzp_test_` keys
- `api/` — REST: `/v1/evaluate`, `/v1/webhooks/razorpay`, `/v1/payments`, `/v1/evaluation/metrics`, `/v1/threshold{/curves,/recommend,/check}`, `/health`, `/ready`
- `app.py` — Dashboard, Agent Policy, Payment Request, Risk Assessment, AI Investigation, Decision Simulator, Payment History, Real World (IEEE), Evaluation & Thresholds, Help, Audit Log
- `database/` — SQLite WAL, 9 tables + `razorpay_events`; `core/logger.py` redaction

## 4. ML results (real IEEE-CIS held-out test — 3,000 temporal rows)

Reproduce: `python evaluation/run_evaluation.py` → `evaluation/results.json` + `evaluation/report.md`

| Metric | @ threshold 0.5 | @ best-F1 threshold (~1.0) |
|---|---|---|
| Precision | 0.0895 | 1.0 |
| Recall | 0.8229 | 0.1771 |
| F1 | 0.1614 | 0.3009 |
| False Positive Rate | 0.2769 | 0.0 |
| False Negative Rate | 0.1771 | 0.8229 |
| Confusion (TN,FP,FN,TP) | 2100, 804, 17, 79 | 2904, 0, 79, 17 |

- **PR-AUC 0.3145** · **ROC-AUC 0.8419** (3.2% fraud rate — PR-AUC is the honest headline, not accuracy)
- Training: 14,450 rows (chunked, no leakage) · validation 2,550 · held-out test 3,000 (temporal split, untouched during tuning)
- SIMULATED cost trade-off: min expected total cost at p=1.0 (block nothing — with these cost weights FP cost exceeds fraud exposure); the tool surfaces the trade-off instead of picking for you
- Synthetic demo model: precision/recall 1.0 — **explicitly not** a production-performance claim (`evaluation/ml_report.json` disclaimer)

## 5. AI capabilities

- Advisory investigation over **structured facts only** (no free-text invention, no score invention)
- Provider abstraction: OpenRouter → Groq → Gemini → local Ollama → **deterministic fallback** (never fails offline)
- Circuit breaker per provider (failure threshold, open/half-open recovery) + OpenRouter fallback-model chain on 429
- Tracks latency, token usage, success/failure, fallback usage

## 6. Failure recovery

| Failure | Behavior |
|---|---|
| Duplicate webhook | `event_id` + payload-hash idempotency → safely ignored |
| AI provider down | Circuit breaker opens → next provider → deterministic fallback |
| No LLM keys at all | Deterministic explanation — everything still works |
| Bad webhook signature | Rejected (raw-body HMAC, constant-time compare) |
| Invalid payloads | Pydantic validation (`models/payment_request.py`), structured errors |
| Webhook processing failure | Retry with backoff → DLQ (`WEBHOOK_MAX_RETRIES`, `WEBHOOK_DLQ_MAX_SIZE`) |

## 7. Security

- Razorpay **TEST MODE enforced in code** (`rzp_test_*` check; live keys refused)
- Secrets only via `.env` (gitignored); `.env.example` committed; no secrets in logs (redaction in `core/logger.py`); audit log stores no sensitive fields
- API key auth on REST (`X-API-Key`); defense-only — no offensive functionality anywhere

## 8. Known limitations (honest)

- Local prototype: SQLite, no JWT/RBAC/rate limiting (stubs in `core/config.py`), no live Razorpay money
- Synthetic labels are not real fraud truth; synthetic generator (550 rows) is a smoke test — real-data evidence comes from IEEE-CIS
- Logistic regression on IEEE features is a baseline; PR-AUC 0.31 is modest — shown honestly, threshold tool lets judges explore the FP-cost trade-off
- Brief's incident/verification engines (clusters, post-action before/after exposure) are not in this track; `ai-payment-copilot/` holds the React+FastAPI+Postgres+Redis production prototype (no tests yet)
- Counterfactual costs are SIMULATED assumptions from config, clearly labeled — never presented as real forecasts

## 9. How to run

```powershell
cd paytrust-ai
pip install -r requirements.txt
python data/synthetic.py                      # seed demo data
python -m models.ml_risk --train data/synthetic_transactions.csv --seed 42   # optional
python evaluation/run_evaluation.py           # → evaluation/results.json + report.md
streamlit run app.py                          # dashboard → http://localhost:8501
python -m api.main                            # REST API → http://localhost:8000 (/docs)
python -m pytest tests/ -q                    # 128 tests
```

## 10. How to demo

Follow `docs/DEMO.md` (judge script). Short version:

1. Dashboard (health, metrics) → 2. Agent Policy (rules are law) → 3. Payment Request (25k → ALLOW; 65k → DENY `max_transaction_exceeded`; gambling → DENY `category_blocked`; 35k → ASK_USER `requires_approval`) → 4. Risk Assessment (7 dimensions) → 5. AI Investigation (fact-bound explanation) → 6. Decision Simulator (counterfactual costs) → 7. Real World (IEEE) + Evaluation & Thresholds (honest held-out metrics) → 8. Audit Log.

## 11. Future improvements

- Postgres + Redis + JWT/RBAC + rate limiting (carry over `ai-payment-copilot/` stack)
- Calibrated probabilities, stronger models on full IEEE, PR-AUC tuning
- Incident/verification engines (clusters, post-action exposure measurement)
- Prometheus/Grafana + OpenTelemetry; Hugging Face Spaces deployment

