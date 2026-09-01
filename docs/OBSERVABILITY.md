# OBSERVABILITY.md — Phase 15

## Logging

- **Library:** `core/logger.py:1` — `RedactingFormatter` + `RequestIdFilter` (ContextVar) + `get_request_id()` (12-hex). All loggers via `get_logger(name)` share redaction and request_id.
- **Format:** `%(asctime)s | %(levelname) | %(name)s | req=%(request_id)s | %(message)s` — never includes `api_key`/`secret` (patterns `sk-or-v1-`, `rzp_test_`, `gsk_` redacted).
- **Helper:** `core/logger.py:log_event(logger, level, event_type, message, extra)` — filters `secret`/`api_key` keys from `extra`.
- **Never logged:** `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, full payloads with PII.

## What Is Logged

For every payment evaluation, `core/metrics.py:log_evaluation` logs:

```
EVALUATION request_id=abc123 decision=ALLOW risk=15 level=LOW ms=42.3 err=False req=...
```

Fields: `request_id`, `event_type` (`PAYMENT_EVALUATED`, `WEBHOOK_RECEIVED`, `AI_INVESTIGATION`), `decision`, `risk_score`, `risk_level`, `processing_ms`, `error` (bool, never secret).

Engines log at `INFO` for `Risk assess` (`engines/risk_engine.py`) and `Decision DENY/ALLOW` (`engines/decision_engine.py`) and `Simulator` (`engines/decision_simulator.py`).

## Metrics Dashboard

`core/metrics.py:get_dashboard_metrics()` queries SQLite:

- `total_requests` — `COUNT payment_requests`
- `total_decisions` — `COUNT decisions`
- `by_decision` — `GROUP BY decision` (ALLOW/ASK_USER/DENY)
- `avg_risk`, `max_risk` — `AVG`/`MAX` risk_score
- `high_risk_count` — `risk_level IN (HIGH,CRITICAL)`
- `policy_violations` — `policy_result LIKE '%violations%'` not empty
- `ai_failures` — `audit_logs WHERE event_type=AI_INVESTIGATION AND action=ERROR`
- `razorpay_events` — `total`/`processed`

Displayed in `app.py:Dashboard` as 4 KPI cards + health table + recent decisions DataFrame. Sidebar shows DB size and inspect JSON.

## Audit Logs

`database/database.py:118` `audit_logs(request_id, event_type, actor, action, metadata)` — redacted via `core/security.py:audit_log`. UI `app.py:Audit Log` shows last 100 rows. No secrets.

## How to Verify

```powershell
python -c "from core.metrics import get_dashboard_metrics; import json; print(json.dumps(get_dashboard_metrics(), indent=2))"
python -c "from core.security import security_checklist; import json; print(json.dumps(security_checklist(), indent=2))"
# Run a payment and check logs — request_id should appear in both app logs and audit_logs
```

## Future (Not in Local Prototype)

Prometheus + Grafana, OpenTelemetry, `pytest` latency tracking — add when moving to Postgres track (`ai-payment-copilot`).
