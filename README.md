# PayTrust AI — Local Prototype (Streamlit + SQLite)

> AI-agent payment safety & authorization layer. Controls whether an AI agent may spend on behalf of a user: **Policy → Risk → Evidence → AI Investigation → ALLOW / ASK_USER / DENY → Payment (Test Mode)**.

**Phase 1 — Clean Local Foundation ✓**

Runs locally with minimal infra: **Streamlit + SQLite + Python 3.11/3.12**. Deterministic policy is final; LLM is advisory only.

## Quick Start

```bash
# 1. Create venv (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install
pip install -r requirements.txt

# 3. Configure (optional for Phase 1)
copy .env.example .env
# edit .env only if you need AI keys or Razorpay Test Mode (Phase 9/11)

# 4. Run
streamlit run app.py
# → http://localhost:8501
```

No Docker, Postgres, Redis, or cloud required for Phase 1-10.

## Project Structure (Phase 1)

```
paytrust-ai/
├── app.py
├── pages/
├── core/
│   ├── config.py       # pydantic-settings, sqlite/postgres switch, validation
│   ├── logger.py       # structured logging, secret redaction, request_id
│   └── exceptions.py   # typed hierarchy
├── database/
│   ├── database.py     # SQLite WAL, parameterized SQL, init_db(), inspect_db()
│   ├── models.py       # Pydantic validation boundary
│   └── repositories.py
├── engines/
│   ├── policy_engine.py    # Phase 3 placeholder
│   ├── risk_engine.py      # Phase 5 placeholder
│   ├── decision_engine.py  # Phase 6 placeholder
│   └── ai_engine.py        # Phase 9 placeholder
├── services/
├── models/
├── data/               # paytrust.db (gitignored), synthetic_transactions.csv (Phase 8)
├── tests/              # Phase 2+ pytest suite
├── docs/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Configuration

All env vars via `core/config.py`. SQLite default `DATABASE_URL=sqlite:///./data/paytrust.db`; override to Postgres if needed. Never commit `.env`.

Validated on startup; `validate_for_production()` warns on default `SECRET_KEY` or non-test Razorpay keys.

## Database

`database/database.py:1` is idempotent: creates 8 tables (users, agents, agent_policies, merchants, payment_requests, risk_assessments, decisions, approvals, audit_logs) with FK, JSON arrays for categories, WAL journal. Seed inserts Test User, Shopping Assistant, 4 merchants for demo.

Inspect: sidebar “DB inspect” or `python -c "from database.database import inspect_db; print(inspect_db())"`.

## Phases (from MASTER PROMPT)

- **0** Audit ✓ (`../PROJECT_AUDIT.md`)
- **1** Foundation ✓ (this)
- **2** SQLite persistence (CRUD tests)
- **3** Policy Engine (deterministic, 10 unit tests)
- **4** Payment Request validation
- **5** Risk Engine (deterministic rules, 0-100)
- **6** Decision Engine (ALLOW/ASK_USER/DENY)
- **7** Streamlit UI (8 pages polished)
- **8** Synthetic Data (`data/synthetic_transactions.csv`, seeded)
- **9** AI Engine (OpenRouter→Groq→Gemini→fallback, strict prompts)
- **10** Decision Simulator (counterfactual, SIMULATED labels)
- **11** Razorpay Test Mode (webhook HMAC, .env only)
- **12** Optional ML (PR-AUC etc., only if beats rules)
- **13** Security Hardening
- **14** Testing (`pytest` suite)
- **15** Observability
- **16** Documentation

## Existing Track Preserved

`../ai-payment-copilot/` (FastAPI + PostgreSQL + Redis + React) is kept for production deployment. Local `paytrust-ai/` is the lightweight MVP harness sharing engine logic via future `paytrust_core/` extraction.

## Testing Phase 1

- `streamlit run app.py` renders Dashboard without errors, sidebar navigates 8 pages, DB inspect shows tables.
- No secrets in logs; secret redaction tested via `core/logger.py`.

## License

MIT
