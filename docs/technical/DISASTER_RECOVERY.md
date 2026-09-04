# Disaster Recovery — PayTrust AI

> RTO/RPO targets, backup strategy, and the step-by-step runbook. Honest scope:
> single-node dev today; the production design below is what DEPLOYMENT/SCALABILITY
> build toward.

## Objectives

| Metric | Dev (today) | Production target | Rationale |
|---|---|---|---|
| RTO (recovery time) | minutes (restart process) | ≤ 30 min | stateless app tier → fast reschedule |
| RPO (data loss window) | ≈ 0 (WAL + fsync) | ≤ 5 min | Postgres PITR / WAL shipping |
| Decision integrity | append-only ledger | append-only ledger | audit records are never rewritten |

## What can break, and what happens

| Failure | Blast radius | Automatic behavior | Recovery action |
|---|---|---|---|
| API process crash | in-flight request | uvicorn restarts (compose/k8s) | health probe self-heals |
| LLM provider outage | AI advisory only | circuit breaker opens; deterministic fallback serves | none — degradation is the design |
| Razorpay webhook storm | event intake | idempotency ledger dedupes; DLQ bounded at 1000 | inspect `razorpay_events.status` |
| SQLite file corruption | all local state | — | restore from backup (below) |
| Host loss | node | — | redeploy container + restore DB |
| Bad model artifact | risk scores | `/ready` fails → traffic gated before decisions | redeploy prior `models/*.pkl` version |

## Backups

| Data | Method | Frequency | Retention | Restore drill |
|---|---|---|---|---|
| SQLite `data/paytrust.db` | `.backup` / file copy while WAL checkpointed | daily + before deploys | 7 daily | copy file back, boot, `/ready` green |
| Postgres (prod) | managed PITR + WAL archive | continuous | 30 days | point-in-time restore |
| `models/*.pkl` | versioned artifacts in release storage | per model train | every version | redeploy artifact, `/ready` verifies |
| `.env` secrets | secret manager (not in backups) | on rotate | current + previous | redeploy with restored refs |
| audit_logs export | append-only JSONL → object storage | daily | ≥ 1 year (compliance) | re-import or side-load for auditors |

## Runbook: full node loss (production)

1. **Declare** incident; note time → RTO clock starts.
2. **Provision** replacement container host; deploy image (same tag as last green CI).
3. **Restore DB** to latest PITR snapshot (RPO ≤ 5 min).
4. **Restore models** artifacts; wait for `/ready` = `{"ready": true, "models": {...true}}`.
5. **Rotate** `PAYTRUST_API_KEY` if compromise suspected; merchants reconfigure.
6. **Replay DLQ** if webhook intake lagged: entries in `razorpay_events` with
   `status != processed` re-enter processing (idempotency keeps this safe).
7. **Verify** with the PRACTICAL_WALKTHROUGH.md decision cases (25000→ALLOW,
   65000→DENY, gambling→DENY) and an HMAC-signed test webhook.
8. **Postmortem**: export `audit_logs` window, file findings.

## Runbook: LLM provider outage

Nothing to do — this is a designed degradation: circuit breaker opens after 5
failures, responses carry `provider: deterministic, fallback_used: true`, decisions
are unaffected. Optionally set `OPENROUTER_FALLBACK_MODELS` to a paid model to
restore advisory depth faster.

## Data integrity guarantees

- Decisions/audit rows are insert-only; no code path updates or deletes them.
- `request_id` ties payment → policy result → risk → decision → audit into one
  replayable evidence chain.
- Webhook idempotency is enforced at the storage layer (unique `payload_hash`),
  so at-least-once delivery never double-processes.
