# TESTING.md — Phase 14

## Strategy
All engines are deterministic and tested in isolation plus end-to-end. Tests use **temporary SQLite files** (`tempfile.TemporaryDirectory` + `init_db(seed=True, db_path=tmp)`) so they never touch `data/paytrust.db` and never require Docker/Postgres.

## How to Run

```powershell
chcp 65001; $env:PYTHONUTF8="1"
cd S:\Buildathon\paytrust-ai
python -m pytest tests/ -v --tb=short
# or per file:
python -m pytest tests/test_policy_engine.py tests/test_risk_engine.py -v
python -m pytest tests/test_database.py -k "test_persistence"
```

Expected after Phases 10-16: **~80+ tests, all pass** (previously: Phase 4 had 40). If shell is deadlocked from earlier `₹` print, run `taskkill /F /IM python.exe` first in an external PowerShell.

## Coverage

| File | Cases | Focus |
|------|-------|-------|
| `tests/test_database.py` | 15 | init, seed, insert/read/update, duplicate email, invalid email, invalid merchant, payment request, daily_spent, FK violation, unique request_id, no api_key column, persistence after restart, parameterized queries, redaction, inspect |
| `tests/test_policy_engine.py` | 12 | 10 required: valid purchase, amount>max, daily limit, blocked category, allowed category, approval threshold, unauthorized agent, restricted merchant (blocked+allowlist), missing policy (DB), invalid data, DB valid flow, DB daily limit |
| `tests/test_payment_validation.py` | 13 | valid, negative/zero/too-large amount, invalid currencies, missing user/agent, invalid category, malformed request_id/merchant_name/timestamp, category normalized, optional fields, timestamp normalized, to_db_dict |
| `tests/test_risk_engine.py` | 11 | LOW normal, MEDIUM spending, HIGH gambling critical, policy violation boost, agent auth critical, frequency, new user, new merchant, deterministic, capping 100, invalid amount |
| `tests/test_decision_engine.py` | 13 | ALLOW low+pass, ASK medium, ASK low+approval, DENY high/critical, DENY violation even if low/high, thresholds 30/60/80, reasons, convenience `decide_for_request` |
| `tests/test_ai_engine.py` | 9 | facts structured, deterministic, offline, OpenRouter success mocked, OpenRouter→Groq fallback, all-fail→deterministic, malformed JSON fallback, invalid key, app usable without AI |
| `tests/test_synthetic.py` | 6 | seed reproducibility, scenarios, CSV readable, distributions, no PII, overwrite deterministic |
| `tests/test_integration.py` | 4 | e2e ALLOW, e2e DENY blocked, e2e ASK medium, DB failure graceful |
| `tests/test_simulator.py` | 5 | ALLOW low cheap, DENY on violation, high risk not ALLOW, medium ASK, all SIMULATED labels |
| `tests/test_razorpay.py` | 6 | HMAC correct, raw body vs parsed, hash, idempotency duplicate, invalid sig rejected, invalid JSON |
| `tests/test_security.py` | 5 | no secrets in DB, audit redaction, sanitize, checklist, SQL injection |
| **Total** | **~80** | |

## Key Invariants Tested

- **Policy is final:** `unauthorized_agent` → `DENY` even if risk LOW (`test_decision_engine`).
- **Risk is deterministic:** same input → same output (`test_risk_engine:deterministic`).
- **AI is advisory:** even when AI fails, decision unchanged (`test_integration:e2e_allow`, `test_ai_engine:app_usable`).
- **No secrets:** `has_api_key_column is False`, audit redacts (`test_security`).
- **Idempotency:** duplicate webhook → `duplicate` not reprocessed (`test_razorpay`).
- **Reproducibility:** same seed → same synthetic rows (`test_synthetic`).

## Edge Cases

- Amount 0, negative, 20M, non-numeric string (`test_payment_validation`).
- Category `""`, `"   "`, `"crypto"`, upper-case normalization.
- Timestamp `not-a-date`, `+05:30` → normalized to `Z`.
- Policy with `is_active=False`, missing policy, `daily_limit` exceeded via `get_daily_spent`.
- Risk with `transactions_last_hour=12`, `user_total_txns=1`, `is_new_merchant`.
- Webhook with `{"a":1}` vs `{"a": 1}` (raw body matters).

## Failures Simulated

- LLM timeout / `invalid_api_key` / malformed JSON → fallback (`test_ai_engine`).
- Razorpay duplicate event → idempotent ignore (`test_razorpay`).
- SQL injection payload → stored literally (`test_security`).
- DB FK violation → `DatabaseError` (`test_database`).

## Manual Checks (Phase 7, 15)

- `streamlit run app.py` → Dashboard metrics, create policy, create payment, evaluate, view risk factors, AI investigation, simulator, history, audit.
- `python -m data.synthetic --normal 500 --anomalies 50 --seed 42` → `data/synthetic_transactions.csv` + distribution print.
- `python -m models.ml_risk --train data/synthetic_transactions.csv --seed 42` → `evaluation/ml_report.json` (PR-AUC, precision, recall).

## CI (Future)

`pytest` must pass before every major milestone. Add `pytest-cov` and threshold in `pyproject.toml` if desired.
