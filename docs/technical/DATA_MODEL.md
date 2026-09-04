# Data Model — PayTrust AI

> SQLite (dev) via `sqlite:///./data/paytrust.db`; production swaps to Postgres with
> the same repository interface (`DATABASE_URL` override). 10 tables, append-only
> decision/audit records, WAL mode enabled.

## Entity–relationship overview

```
users 1───* agent_policies *───1 agents
  │                    │
  1                    1
  │                    │
payment_requests *─────┘ (user_id + agent_id + merchant_id)
  │ 1
  ├────* decisions 1────* approvals
  ├────* risk_assessments
  ├────* audit_logs
merchants 1────* payment_requests
razorpay_events (standalone idempotency ledger for webhook deliveries)
```

## Tables (real DDL summary from `database/models.py`)

| Table | Key columns | Purpose |
|---|---|---|
| `users` | id, email, name, role, password_hash | Account owners; roles for RBAC |
| `agents` | id, agent_name, description, is_active | AI agents allowed to initiate payments |
| `agent_policies` | user_id, agent_id, daily_limit, max_transaction, approval_threshold, allowed_categories, blocked_categories, allowed_merchants, blocked_merchants, is_active | The "policy is law" config consumed by PolicyEngine |
| `merchants` | id, name, category, region, risk_tier | Merchant registry |
| `payment_requests` | request_id (unique), user_id, agent_id, merchant_id, merchant_name, amount, currency, category, description, agent_reason, status | Every incoming evaluation request |
| `decisions` | request_id, decision (ALLOW/ASK_USER/DENY), risk_score, risk_level, policy_result (JSON), reasons (JSON), ai_explanation | Immutable decision record |
| `risk_assessments` | request_id, risk_score, risk_level, factors (JSON), model_version | 7-dimension risk factor evidence |
| `approvals` | decision_id, approver, status, reason, decided_at | Human-in-the-loop outcomes for ASK_USER |
| `audit_logs` | request_id, event_type, actor, action, metadata (JSON) | Append-only audit trail (no updates/deletes) |
| `razorpay_events` | event_id, event_type, payment_id, payload_hash (unique), status, error_message | Webhook idempotency ledger + DLQ |

## Conventions & integrity rules

- **request_id** is the global correlation key across `payment_requests`,
  `decisions`, `risk_assessments`, `audit_logs` — one evaluation, one trail.
- **JSON columns** (`policy_result`, `reasons`, `factors`, `metadata`) store the
  full evidence payload so records are self-contained and replayable.
- **Append-only**: `decisions`, `audit_logs`, `razorpay_events` are never updated
  (except DLQ status transitions on `razorpay_events`).
- **Money** stored as integer minor units / INR floats at the API edge; the
  decision engine never mutates amounts.
- **Timestamps** UTC, stored ISO-8601 (`created_at`/`updated_at`).

## Indexes & performance

- Unique: `payment_requests.request_id`, `razorpay_events.payload_hash`, `users.email`.
- Lookup paths: all `request_id` foreign lookups; `audit_logs.created_at` for the
  UI audit feed; `agent_policies(user_id, agent_id, is_active)` for the hot policy fetch.
- SQLite pragmas: WAL (concurrent reads during writes), foreign_keys ON.

## Retention & lifecycle

| Data | Retention | Rationale |
|---|---|---|
| decisions + audit_logs | keep (append-only ledger) | Regulatory traceability |
| payment_requests | keep | Referenced by decisions |
| razorpay_events | keep latest 1000 DLQ entries (`WEBHOOK_DLQ_MAX_SIZE`) | Bounded DLQ |
| data/paytrust.db* | gitignored; regenerate via app bootstrap + seed | Dev convenience |

## Migrations

- Dev: schema auto-created at boot (`database/database.py`) — no migration tool needed.
- Production: switch `DATABASE_URL` to Postgres; repositories are the only DB
  touchpoint, so table definitions map 1:1 (JSON columns → JSONB).
