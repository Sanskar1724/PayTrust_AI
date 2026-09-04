# Business Model — PayTrust AI

> How PayTrust AI makes money, what it costs, and the path to profitability.

---

## 1. Value proposition

**For merchants:**
- **Reduce fraud losses** by 30–60% (industry average for ML-powered detection)
- **Reduce false-positive cost** (customer friction, support tickets, lost LTV) by 20–40%
- **Defensible audit trail** for regulator inquiries
- **AI-native**: built for the agentic-commerce era; no retrofitting needed

**For AI agent platforms:**
- A safe way for agents to spend money on behalf of users
- Liability reduction: the merchant + PayTrust share the safety burden
- Drop-in SDK, not a 6-month integration

**For end users:**
- Trust: no unauthorized spend, easy approval flow when needed
- No new app to install; flows surface in the agent's existing UI

---

## 2. Pricing tiers

We use a **usage-based + tiered SaaS** model. SaaS is the floor; usage scales with the merchant.

---

## 3. Unit economics

### 3.1 Variable cost per evaluation (at 50k/month tier)

| Component | Cost / eval |
|---|---|
| ML inference (sklearn, in-process) | ₹0.001 |
| Audit log write (Postgres + S3 archive) | ₹0.005 |
| AI investigation (if invoked, ~30% of evals) | ₹0.50 |
| Edge / CDN / observability share | ₹0.05 |
| **Total variable cost** | **₹0.20** (if AI invoked), **₹0.06** otherwise |

### 3.2 Blended per-evaluation revenue (Growth tier, AI invoked 30% of time)

- Tier revenue: ₹25,000 / 50,000 = **₹0.50 per eval** (before AI add-on)
- AI add-on: 0.3 × ₹2 = **₹0.60 per eval**
- **Blended ARPU: ₹1.10 per eval**

### 3.3 Gross margin

- Revenue ₹1.10 – Cost ₹0.20 = **₹0.90 / eval → 82% gross margin** at the unit level
- After fixed cost allocation (engineering, support, hosting) we expect **50–65% EBITDA margin at scale**

---

## 4. Customer acquisition cost (CAC) & lifetime value (LTV)

| Channel | Estimated CAC | Notes |
|---|---|---|
| Direct sales (enterprise) | ₹2,00,000 | 1 sales rep, 3-month sales cycle |
| PSP partner co-sell | ₹50,000 | PSPs introduce us to their merchants |
| AI-agent platform listing | ₹20,000 | "Install in 1 click" model |
| Self-serve (Growth tier) | ₹10,000 | Content marketing + community |
| Free tier → paid conversion | ₹2,000 | Product-led growth |

**LTV assumption:** average customer stays 36 months, expands usage 2× over lifetime.
- Growth tier: ₹25k × 36 months × 1.5 (expansion) = **₹13.5L LTV**
- Scale tier: ₹1.5L × 36 months × 1.5 = **₹81L LTV**
- LTV/CAC: **5–10×** at scale → healthy SaaS economics

---

## 5. Revenue forecast (conservative)

| Year | Paying customers | ARPU / month | ARR |
|---|---|---|---|
| Y1 (2026) | 25 | ₹30,000 | **₹90L** (~USD 108k) |
| Y2 (2027) | 200 | ₹40,000 | **₹9.6Cr** (~USD 1.15M) |
| Y3 (2028) | 1,000 | ₹50,000 | **₹60Cr** (~USD 7.2M) |
| Y5 (2030) | 10,000 | ₹60,000 | **₹720Cr** (~USD 86M) |

**Key assumptions:**
- Y1: 25 design-partner merchants, mostly Growth tier
- Y2: PSP partnership begins driving channel sales
- Y3: AI-agent platform listings unlock 10× growth in customer count
- Y5: international expansion (SE Asia, Europe)

---

## 6. Pricing strategy notes

- **Why usage-based?** Fraud detection value scales with transaction volume. The more transactions we protect, the more the merchant saves.
- **Why not 100% pay-per-eval?** Free tier + predictable tiers reduce friction for adoption. Many merchants want budget certainty.
- **Why AI as a separate add-on?** Most merchants don't need LLM explanations for every decision — the dashboard is enough. AI investigation is for the 5–10% of decisions that need human review.
- **Discounting:** Annual contracts get 15% off. Multi-year (3yr) get 25% off. This locks in customer commitment.
- **Avoid:** Per-seat pricing (doesn't fit the use case), per-API-call pricing (discourages adoption).

---

## 7. Competitive moat

1. **Evidence-driven UX** — most fraud tools say "block 17 transactions" with no explanation. We say "block 17 because: factor A (severity high, +25), factor B (severity medium, +10), policy violation X". Differentiable.
2. **AI-native architecture** — built for agentic commerce from day 1. Legacy players are retrofitting.
3. **Counterfactual engine** — unique in the industry. Lets merchants see the cost of each action.
4. **Held-out ML on real data (IEEE-CIS 590k)** — not synthetic, not marketing-tuned. PR-AUC 0.31 is modest but honest.
5. **Buildathon provenance** — built in 8 weeks with a small team; agile and focused.

---

## 8. Path to profitability

| Stage | Timeline | Investment | Revenue target |
|---|---|---|---|
| Seed | Now → Y1 | ₹2Cr | ₹90L ARR |
| Series A | Y1 → Y2 | ₹15Cr | ₹9.6Cr ARR |
| Series B | Y2 → Y3 | ₹50Cr | ₹60Cr ARR |
| Profitability | Y3 → Y4 | — | Break-even |
| Default-alive | Y2 | — | ₹30Cr+ ARR, growth rate > 100% |

---

## 9. Risks to the business model

- **Regulatory:** RBI mandates on AI payment agents could force architecture changes.
- **AI commoditization:** If a PSP builds a similar feature in-house, we lose the partnership channel. **Mitigation:** Be the best, lock in via multi-year contracts, be default-recommended by 2+ PSPs.
- **Loss of payment-provider neutrality:** If we go deep with Razorpay, Stripe/Adyen merchants may not trust us. **Mitigation:** Stay provider-neutral; integrations are pluggable.
- **False-positive litigation:** A merchant blocked from selling loses revenue. **Mitigation:** Counterfactual engine, easy override, appeal workflow.
- **Fraud-ring adaptation:** Adversaries adapt to our detection. **Mitigation:** Continuous retraining, anomaly detection, human-in-the-loop for novel patterns.

---

## 10. Key metrics we track

| Metric | Target |
|---|---|
| Free → paid conversion | > 8% within 90 days |
| Net revenue retention | > 120% (expansion via usage growth) |
| Gross margin | > 75% |
| Logo churn | < 5% annual |
| LTV / CAC | > 5× |
| Time to first decision | < 5 min after signup |
| Inference P95 | < 200ms |
| Uptime | > 99.9% |

| Tier | Monthly fee | Included evaluations | Overage | Best for |
|---|---|---|---|---|
| **Starter** | ₹0 (free forever) | 1,000 / month | ₹1 per eval | Indie developers, hobby agents |
| **Growth** | ₹25,000 / month | 50,000 / month | ₹0.50 per eval | D2C startups, small SaaS |
| **Scale** | ₹1,50,000 / month | 500,000 / month | ₹0.30 per eval | Mid-market e-commerce, B2B SaaS |
| **Enterprise** | Custom | Custom | Volume discount | Large merchants, PSPs |

**Per-event add-ons:**
- AI Investigation (advisory LLM call): **₹2 per call** at all tiers (covers the LLM token cost + a small margin)
- Dedicated policy-engineer support: **₹3,00,000 / month**
- White-label dashboard: **₹5,00,000 / month** + ₹50,000 / month per custom domain
