# Deployment — PayTrust AI

> Four supported targets, from zero-install local to container cloud. All configs
> referenced here exist in the repo (`Dockerfile`, `docker-compose.yml`).

## 1. Local (fastest — recommended for judges)

```powershell
cd S:\Buildathon\paytrust-ai
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# optional: create .env from template (app runs without it)
Copy-Item .env.example .env

# Terminal 1 — REST API
python -m api.main                 # http://localhost:8000  (docs at /docs)

# Terminal 2 — Dashboard
streamlit run app.py               # http://localhost:8501
```

Print the dev API key: `python -c "from api.security import api_key_for; print(api_key_for())"`

## 2. Docker (single container)

```powershell
docker build -t paytrust-ai .
docker run -p 8000:8000 -p 8501:8501 --env-file .env paytrust-ai
```

`Dockerfile` installs from `requirements.txt`, copies app + api + engines +
services + database + models + evaluation assets, and launches both processes.

## 3. Docker Compose (batteries included)

```powershell
docker compose up --build
```

- `api` service on :8000, `streamlit` service on :8501
- volume mounts for `data/` so the SQLite ledger survives rebuilds
- secrets come from `.env` (never baked into the image)

## 4. Hugging Face Spaces (free public URL)

1. Create a Space → Docker type → push this repo.
2. Set Space secrets: `PAYTRUST_API_KEY`, `OPENROUTER_API_KEY`, (optional)
   `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` —
   **`rzp_test_` keys only** (live keys are refused by code).
3. Space serves the API; expose Streamlit via the same container on the assigned port.

## Environment variable matrix (from `core/config.py`)

| Var | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | prod: yes | `change-me-...` | min 32 random chars; seeds dev API key |
| `PAYTRUST_API_KEY` | prod: yes | unset → derived dev key | header `X-API-Key` |
| `CORS_ALLOW_ORIGINS` | prod: yes | `*` (dev only) | comma-separated allowlist |
| `DATABASE_URL` | no | `sqlite:///./data/paytrust.db` | Postgres URL for production |
| `RAZORPAY_KEY_ID/SECRET` | no | unset | **TEST MODE ONLY** (`rzp_test_*` enforced) |
| `RAZORPAY_WEBHOOK_SECRET` | no | unset | HMAC verify of raw webhook body |
| `OPENROUTER_API_KEY` | no | unset | enables AI advisory (httpx REST) |
| `OPENROUTER_MODEL` | no | `google/gemma-4-31b-it:free` | + `OPENROUTER_FALLBACK_MODELS` on 429 |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | no | unset | fallback providers 2 and 3 |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434` | local LLM option |
| `CB_FAILURE_THRESHOLD` / `CB_RECOVERY_TIMEOUT` | no | 5 / 60 | circuit breaker per provider |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW` | no | 100 / 60 | per-process limiter |
| `RISK_THRESHOLD_LOW/MEDIUM/HIGH` | no | 30 / 60 / 80 | documented banding |
| `FP_*`, `FN_*` | no | see `.env.example` | SIMULATED cost model assumptions |
| `WEBHOOK_MAX_RETRIES` / `WEBHOOK_RETRY_DELAY` / `WEBHOOK_DLQ_MAX_SIZE` | no | 3 / 5 / 1000 | webhook reliability |

The app **boots with none of the optional vars** — decisions are fully
deterministic; AI advisory degrades to the deterministic provider.

## Health & smoke checks after deploy

```powershell
curl http://localhost:8000/health      # {"status":"ok",...}
curl http://localhost:8000/ready       # {"ready":true,...}
curl http://localhost:8501/_stcore/health   # ok
```

## CI

GitHub Actions (`.github/workflows/ci.yml`): install → compile → `pytest` (128)
→ threshold smoke — runs on push/PR.
