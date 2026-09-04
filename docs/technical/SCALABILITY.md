# Scalability — PayTrust AI

> Current architecture → bottleneck analysis → concrete scaling path.

## Current (dev) topology

```
Streamlit UI (:8501) ─┐
                      ├─ same engines/services ─── SQLite (WAL) ── models/*.pkl
FastAPI (:8000) ──────┘
```

Single node, stateless app tier, all state in SQLite + model files. This honestly
serves a merchant demo / pilot (~10k evaluations/day) with p95 ≈ 15 ms decisions.

## Bottleneck analysis (in the order they bite)

| # | Bottleneck | Symptom | Threshold (approx) | Fix |
|---|---|---|---|---|
| 1 | SQLite write contention | `database is locked` spikes | > ~50 writes/s sustained | → Postgres (`DATABASE_URL`), repositories already abstract it |
| 2 | Sync LLM latency on `investigate=true` | slow responses if awaited inline | any provider > 12 s | already bounded: 12 s timeout + circuit breaker; move to queue+poll for >50 rps |
| 3 | In-process rate limiting | limits don't aggregate across replicas | 2+ API replicas | Redis token bucket |
| 4 | Threshold/eval endpoints re-reading parquet | CPU spike per call | large held-out sets | cache loaded curves in-process (they're static per model version) |
| 5 | Streamlit session footprint | RAM per session | hundreds of concurrent users | Streamlit is the control plane only — real traffic hits the API; keep UI internal |

## Scaling path (staged)

1. **Vertical (day 1)**: 2 vCPU / 4 GB handles API + UI + SQLite comfortably.
2. **Split DB (first scale-out)**: Postgres managed instance; zero app-code change
   (`DATABASE_URL=postgresql+asyncpg://...`), JSON columns → JSONB.
3. **Stateless API replicas**: uvicorn workers/containers behind a load balancer;
   engines are pure functions over request state — no sticky sessions needed.
4. **Async AI path**: webhook → queue (Redis Streams / SQS) → worker pool for
   `investigate=true` batches; decision endpoints stay synchronous-fast.
5. **Multi-region (later)**: read replicas + region-pinned writes; audit log is
   append-only so it ships to object storage per region cleanly.

## Capacity planning (ESTIMATED — labeled per repo convention)

| Load | Nodes | DB | Notes |
|---|---|---|---|
| 1k tx/day | 1 | SQLite | dev default, zero tuning |
| 10k tx/day | 1–2 | SQLite WAL or small Postgres | still single AZ |
| 100k tx/day | 2–3 API + queue worker | Postgres + read replica | Redis for rate limits + queue |
| 1M tx/day | 5–10 API + worker autoscaling | partitioned Postgres + OLAP mirror for analytics | audit log → object storage |

All numbers are engineering estimates, not benchmarks — load-test with `locust`
before committing SLAs (see NFR-3 gap in NON_FUNCTIONAL_REQ.md).

## What does NOT scale (by design, and why that's fine)

- **Streamlit dashboard** — operator/judge tool, not a customer-facing surface.
- **IEEE-CIS threshold tool** — static per model version; served from cache.
- **Deterministic fallback provider** — stateless by construction; it's the safety
  net that keeps the decision path scalable regardless of LLM health.
