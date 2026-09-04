# Service Providers — PayTrust AI

> Vendor evaluations for every external dependency. Selection rule: no vendor lock
> in the decision path — the LLM tier is swappable, the payment tier is the
> merchant's choice, everything else is open source or portable.

## Payment infrastructure (integrated)

| Provider | Role | Status | Why / notes |
|---|---|---|---|
| **Razorpay** | Payment gateway + webhooks | ✅ integrated (TEST MODE enforced) | Buildathon sponsor; raw-body HMAC verification, idempotent event ledger, DLQ. `rzp_test_*` keys only — live keys refused by code. `services/razorpay_service.py` |
| Stripe / Adyen | alternative gateways | 📋 not integrated | Webhook-HMAC pattern generalizes; isolate in `services/` |

## AI / LLM (advisory tier — swappable chain)

| Provider | Role | Status | Notes |
|---|---|---|---|
| **OpenRouter** | primary LLM gateway | ✅ live-verified | Model `google/gemma-4-31b-it:free`, auto-fallbacks `google/gemma-4-26b-a4b-it:free, openrouter/free` on 429; polite client retry; key confirmed working 2026-09-02 |
| **Groq** | LLM fallback #2 | 🟡 configured, key unset | `llama-3.1-70b-versatile` via OpenAI-compatible REST |
| **Google Gemini** | LLM fallback #3 | 🟡 configured, key unset | REST; same fact-bound prompt |
| **Ollama** | local LLM option | 🟡 configured | `OLLAMA_BASE_URL` — fully offline advisory |
| **Deterministic provider** | final fallback | ✅ always available | Rule-based explanation; keeps product functional with zero vendors |

Chain: OpenRouter → Groq → Gemini → deterministic. Circuit breaker
(5 failures → open 60 s) per provider. **No SDK lock-in**: all providers are plain
`httpx` REST calls (`engines/ai_engine.py`).

## Data & ML

| Provider | Role | Status | Notes |
|---|---|---|---|
| **IEEE-CIS Fraud Detection (Kaggle)** | real-world training/eval data | ✅ integrated | 590k rows, temporal split; PR-AUC 0.314 held-out; raw CSVs gitignored, provenance documented |
| scikit-learn | Logistic + IsolationForest | ✅ | models/*.pkl, versioned via `model_version` columns |
| SQLite / PostgreSQL | storage | ✅ / 📋 | same repository interface, `DATABASE_URL` swap |

## Cloud & runtime (planned options)

| Provider | Role | Status | Notes |
|---|---|---|---|
| **Hugging Face Spaces** | free public hosting | 📋 Dockerfile ready | zero-cost demo URL |
| Railway / Render / Fly.io | managed containers | 📋 | compose translates directly |
| AWS / GCP | production scale | 📋 | see SCALABILITY.md staged path |

## Observability

| Provider | Role | Status | Notes |
|---|---|---|---|
| structlog | JSON logging | ✅ | redaction built in |
| `/health`, `/ready` | probes | ✅ live | k8s/compose compatible |
| Prometheus / Grafana / Sentry | metrics, dashboards, errors | 📋 | `core/metrics.py` is the seam |

## Procurement summary (ESTIMATED)

- **$0/month** achievable for pilot: OpenRouter free tier + HF Spaces + SQLite.
- First paid tier typically: managed Postgres (~$15) + LLM pay-per-token (~$10–50)
  + container hosting (~$10) — detailed in COST_ESTIMATION.md.
- Exit strategy per vendor: all integrations sit behind thin service/adapter
  modules; the decision engine never calls a vendor directly.
