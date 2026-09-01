# DEPLOYMENT.md — Serving PayTrust AI (free-first, 8 GB laptop friendly)

The local footprint is intentionally tiny — no Postgres/Redis/Docker required on
your 8 GB laptop. The trained models are ~0.01 MB and prediction is near-zero RAM.
You can serve people entirely from free tiers.

## 1. Run locally (dev)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # fill only if you want AI/Razorpay TEST keys
streamlit run app.py            # dashboard  http://localhost:8501
python -m api.main              # API        http://localhost:8000  | /docs
```

Both processes share the same SQLite file (WAL mode) — safe on one host.

## 2. Single-host with Docker (reference)

```powershell
copy .env.example .env          # set SECRET_KEY, PAYTRUST_API_KEY, CORS_ALLOW_ORIGINS
docker compose up --build -d
```

Not needed locally — provided so the same code runs on any $5 VPS later.

## 3. Free public hosting — Hugging Face Spaces (Docker) ← recommended

One Space runs **both** the FastAPI API and the Streamlit dashboard behind one URL.

1. Push this repo (`paytrust-ai/`) to GitHub.
2. Create a **Docker** Space on https://huggingface.co/new-space
   - SDK: **Docker**
   - `Dockerfile` → use this repo's Dockerfile (runs the API by default).
   - To expose the dashboard too, override the Space entrypoint:
     `python -m streamlit run app.py --server.port 7860 --server.address 0.0.0.0`
     (HF Spaces proxy expects port **7860**; map the API on an internal port and
     add a small reverse proxy OR run the dashboard as the main app and the API
     on `:8000` — see note below).
3. Set Space secrets (Settings → Variables and secrets):
   `SECRET_KEY`, `PAYTRUST_API_KEY`, `CORS_ALLOW_ORIGINS`, optional LLM/Razorpay TEST keys.
4. Open the Space URL → dashboard live; hit `https://<space>.hf.space/health`.

**Two services, one Space (recommended layout):** add a tiny `Dockerfile` CMD that
starts both via a wrapper (e.g. `python run_both.py`): uvicorn on `:8000` and
streamlit on `:7860`. The Space serves `:7860` publicly; the API stays fully
functional internally and can be exposed on `/` via `streamlit` for the demo.
For a public API gateway later, move the API to Render + managed Postgres/Redis.

## 4. Memory budget (8 GB laptop)

| Component | Peak RAM |
|---|---|
| Streamlit app | ~300 MB |
| FastAPI service | ~150 MB |
| SQLite + models | < 50 MB |
| Total | **~500 MB** — fits comfortably. |

No Postgres/Redis/Docker on the laptop = nothing fights for the 0.7 GB you have free.

## 5. Env checklist (production)

Required: `SECRET_KEY` (≥32 random), `PAYTRUST_API_KEY` (strong random),
`CORS_ALLOW_ORIGINS` (explicit allowlist, never `*`).
Test-mode only: `RAZORPAY_KEY_ID` (`rzp_test_*`), `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`. LLM (optional): `OPENROUTER_API_KEY` / `GROQ_API_KEY` /
`GEMINI_API_KEY`. Without LLM keys the app degrades to deterministic (still works).

## 6. Reliability features already wired

- API-key auth + in-process rate limiting (no Redis needed single-instance)
- Idempotent `/v1/evaluate` (same `request_id` → same decision)
- Razorpay webhook HMAC raw-body verification + duplicate idempotency
- Request-id correlation (`X-Request-ID`) + redacted structured logs
- Deterministic fallback when LLM/network unavailable
- Health/readiness probes for orchestrators
- Production boot guard (refuses unsafe config loudly)