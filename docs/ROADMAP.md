# PayTrust AI — Roadmap & Readiness Checklist

> Track 02 — AI Risk Manager (Razorpay Buildathon). Evidence-driven payment risk & loss prevention.
> What this doc is: the 4-phase plan, the 15 buildathon requirements checklist, and the honest list of what is done / what remains (optional).

## Status summary

- **Tests:** `128 passed` (`python -m pytest tests/ -q`)
- **Streamlit app:** boots → health `200 ok` (`streamlit run app.py`)
- **FastAPI REST:** boots → all 11 routes registered (`/health`, `/ready`, `/v1/evaluate`, `/v1/payments{,/id}`, `/v1/webhooks/razorpay`, `/v1/evaluation/metrics`, `/v1/threshold{,/curves,/recommend,/check}`)
- **Real-world ML:** IEEE-CIS 590k trained in chunks; held-out temporal test 3,000 rows predictions committed → threshold decision tool
- **Repo:** committed at `389ffd5` (includes `ai-payment-copilot` production track).

## The 4-phase plan (what the project is)

| Phase | Scope | Status |
|---|---|---|
| **1 — Foundation & Policy** | Streamlit+SQLite scaffold, config/logger/security, DB (WAL + seed), PolicyEngine (agent authz: daily limit, max tx, approval>, allow/block categories), PaymentRequest validation | ✅ Done |
| **2 — Risk → Evidence → Decision** | RiskEngine (7 dimensions → 0-100 + factors), DecisionEngine (ALLOW/ASK_USER/DENY), DecisionSimulator (counterfactuals, SIMULATED costs), AIEngine (advisory, OpenRouter→Groq→Gemini→deterministic fallback), Razorpay TEST MODE webhooks (HMAC, idempotent), FastAPI REST service | ✅ Done |
| **3 — Measurable ML on real data** | Chunked training on IEEE-CIS 590k (no full load), PR-AUC/ROC/confusion,, threshold decision tool (real held-out test + SIMULATED cost trade-off, UI + REST + tests + docs) | ✅ Done (finished this session) |
| **4 — Hardening & packaging** | `.gitignore` hygiene (ignore 1.3 GB CSVs, processed/, db-shm/wal), docs, tests green, checkpoint commit, optional submission.csv / AI key / HF deploy | ✅ Done (except optional items below) |

## Buildathon-15 requirements → coverage

| # | Requirement | Covered by |
|---|---|---|
| 1 | Real problem | AI-agent payment abuse / fraud-spike detection |
| 2 | Working product | Streamlit 10-page app + FastAPI REST, boots 200 OK |
| 3 | AI meaningfully | Advisory AIEngine (multi-provider fallback) + ML model — AI never overrides deterministic policy |
| 4 | Engineering quality | Typed code, docstrings, 128 tests, 8 docs, UI/API logic reuse |
| 5 | Failure recovery | Circuit breakers, provider fallback chain, idempotent webhooks, graceful degradation |
| 6 | One loss class | Payment abuse / fraud-spike detection (clearly scoped) |
| 7 | Precision | Measured on real IEEE held-out test (report + threshold tool) |
| 8 | Recall | Same — live at every threshold in the tool |
| 9 | Held-out test set | Temporal 15% IEEE test (3,000 rows, predictions committed) |
| 10 | False positives | FPR + confusion matrix (FP/TN) |
| 11 | FP cost | SIMULATED cost model (friction + lost value + support + merchant impact, labeled) |
| 12 | Defense-only | Only authorize / ask / deny / review — no offensive features |
| 13 | Evidence behind decisions | Factors (name/severity/score/details), policy violations, audit trail, fact-bound AI explanation |
| 14 | Honest limitations | README limitations, SIMULATED/ESTIMATED labels, report disclaimers |
| 15 | End-to-end flow | Policy → Risk → Evidence → AI → Simulator → Decision → Persist → Audit (UI + REST) |

## What remains (all optional — core product is ready)

1. **Generate `evaluation/submission.csv`** — 506k test predictions (button in `app.py` → Real World (IEEE) → Generate Submission; or CLI — use the bundled `.venv` (Python 3.12 + scikit-learn) since the system Python 3.14 lacks sklearn):
   ```powershell
   .\.venv\Scripts\python.exe -W ignore -m models.predict_ieee --model models/ieee_model.pkl --out evaluation/submission.csv
   ```
2. **Add a live LLM key** to `.env` (OpenRouter free / Groq / Gemini) — offline it falls back to deterministic explanation (everything still works).
3. **(Optional)** Deploy to Hugging Face Spaces Docker — see `docs/DEPLOYMENT.md` (free tier serves API + dashboard).

## Verified real numbers (held-out IEEE test, honesty — not tuned for marketing)

- PR-AUC `0.314`, ROC-AUC `0.842`, F1 `0.161` @ default 0.5 (logistic) — report `evaluation/ieee_report.json`
- Threshold tool recommendation (SIMULATED cost model,: max F1 `0.294` @ p≈0.96; min SIM total cost @ p=1.0 (block nothing) — see UI / `/v1/threshold/recommend`
- Synthetic demo model: precision/recall `1.0` on the demo set — *explicitly not* a claim of production performance (see disclaimer).

## How to run

```powershell
cd paytrust-ai
pip install -r requirements.txt
streamlit run app.py            # dashboard → http://localhost:8501
python -m api.main            # REST API   → http://localhost:8000  (Swagger /docs)
python -m pytest tests/ -q    # 128 tests
```