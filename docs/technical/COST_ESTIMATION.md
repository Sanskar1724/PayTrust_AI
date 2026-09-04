# Cost Estimation — PayTrust AI

> Monthly infrastructure cost projections. Every number is an **ESTIMATE** based on
> public list prices (Sep 2026) and the repo's measured resource profile — not a quote.

## Assumptions

- Decision path (no AI): ≈ 15 ms CPU per evaluation (measured, `processing_ms`).
- AI advisory on ~10% of evaluations, ≤ 800 tokens per call.
- Storage grows ~2 KB per evaluation (payment + decision + risk + audit rows).
- Single region; Postgres managed; LLM via OpenRouter with free-tier models first.

## Scenario 1 — Pilot / demo (current state)

| Item | Spec | Cost/month |
|---|---|---|
| Hosting | Hugging Face Spaces (free tier) | **$0** |
| Database | SQLite file on container disk | $0 |
| LLM | OpenRouter free models (`*:free`) | $0 |
| Observability | structlog stdout + `/health` | $0 |
| **Total** | | **$0** |

Matches today's live deployment posture — the buildathon demo runs at zero cost.

## Scenario 2 — Early production (10k tx/day ≈ 300k/mo)

| Item | Spec | Cost/month |
|---|---|---|
| Container hosting | 1 vCPU / 2 GB (Railway/Render/Fly) | ~$10–20 |
| Postgres | managed, 10 GB (Neon/Supabase/RDS small) | ~$15–25 |
| LLM | 30k investigations × $0.0002–0.0005 | ~$6–15 |
| Object storage | audit archive < 5 GB | <$1 |
| **Total** | | **≈ $32–61** |

## Scenario 3 — Growth (100k tx/day ≈ 3M/mo)

| Item | Spec | Cost/month |
|---|---|---|
| API nodes | 2–3 × 2 vCPU behind LB | ~$60–120 |
| Postgres | 4 vCPU / 16 GB + read replica | ~$150–300 |
| Redis | rate limit + queue | ~$15–30 |
| LLM | 300k investigations, paid tier | ~$60–150 |
| Observability | managed logs/metrics | ~$30–80 |
| **Total** | | **≈ $315–680** |

## Scenario 4 — Scale (1M tx/day ≈ 30M/mo)

| Item | Spec | Cost/month |
|---|---|---|
| API + workers | 8–12 nodes autoscaled | ~$500–1,000 |
| Postgres | partitioned + OLAP mirror | ~$800–2,000 |
| Redis cluster | HA | ~$100–200 |
| LLM | 3M calls, model routing to cheapest-capable | ~$600–1,500 |
| Observability + storage | logs, metrics, audit archive | ~$200–500 |
| **Total** | | **≈ $2.2k–5.2k** |

## Cost levers (ordered by impact)

1. **LLM routing**: free models first, paid only on fallback — already implemented
   (`OPENROUTER_FALLBACK_MODELS` chain); cap advisory depth with `max_tokens=800`.
2. **Advisory rate**: AI is opt-in per request (`investigate`) — charge it to the
   merchant tier that wants it.
3. **SQLite → Postgres only when needed** (≈ 50 writes/s wall, see SCALABILITY.md).
4. **Audit archive tiering**: object storage after 90 days; ledger stays queryable.

## Unit economics sanity check (ESTIMATED)

At 10k tx/day, $50/mo infra ÷ 300k evaluations ≈ **$0.00017 per decision** — the
deterministic engine is effectively free; LLM advisory dominates variable cost,
which is why it is strictly optional and fallback-protected.
