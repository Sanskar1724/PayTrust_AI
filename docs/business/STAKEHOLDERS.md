# Stakeholders — PayTrust AI

> Who uses, builds, buys, regulates, and competes with PayTrust AI.

---

## 1. Primary stakeholders (direct users)

### 1.1 Merchants
**Role:** The paying customer of PayTrust AI (B2B SaaS).
**Need:** Reduce fraud losses, false-positive losses, and compliance burden.
**How they use it:** Install the agent SDK (or call the REST API), define agent policies in the dashboard, monitor decisions in the Audit Log.
**Success metric:** Reduction in INR lost to fraud per month; reduction in false-positive customer friction cost.
**Representative:** D2C e-commerce platforms, travel booking sites, SaaS billing systems, B2B marketplaces.

### 1.2 AI Agents
**Role:** End-user-facing "buyer" (e.g., OpenAI Operator, Anthropic Computer Use, custom shopping agents).
**Need:** Reliable, low-latency authorization decisions; predictable behavior; graceful failure.
**How they use it:** Call `POST /v1/evaluate` for every payment intent, then either proceed, ask the user, or abandon.
**Success metric:** Sub-200ms P95 response; 99.9% uptime; no silent payment approvals.

### 1.3 End Users (humans)
**Role:** The human on whose behalf the agent is buying.
**Need:** Trust that the agent won't drain their account; easy approval flow when needed.
**How they interact:** Receive ASK_USER prompts, occasionally approve or reject. Never see the dashboard directly.
**Success metric:** No unauthorized spend; no false-positive friction on legitimate purchases.

### 1.4 Risk Operations Team
**Role:** Internal staff at the merchant reviewing flagged decisions.
---

## 2. Secondary stakeholders (influencers & enablers)

### 2.1 Payment Service Providers (PSPs)
**Examples:** Razorpay, Stripe, PayPal, Adyen.
**Interest:** We send them fewer chargebacks, fewer disputes, and (paradoxically) more legitimate volume (because we block less). They can co-market and offer us as an add-on.
**Influence:** PSP partnership program is the primary GTM channel.

### 2.2 AI Agent Platform Providers
**Examples:** OpenAI (Operator / Apps SDK), Anthropic (Computer Use / MCP), Google (Gemini), Microsoft (Copilot).
**Interest:** Their agents need a safe way to spend money. They prefer a third-party, auditable, defense-only layer vs. building it themselves.
**Influence:** Listing in their app stores is the long-term GTM lever.

### 2.3 Cloud & Infrastructure Providers
**Examples:** AWS, GCP, Azure, Hugging Face.
**Interest:** Standard SaaS revenue; we run on their PaaS products.
**Influence:** Pricing, regional availability, SLA, compliance certifications.

### 2.4 LLM Providers (advisory)
**Examples:** OpenRouter (aggregator), Groq, Google Gemini, Ollama (self-hosted).
**Interest:** Token revenue from the advisory call. We use them for the explanation step, not the policy decision.
**Influence:** Pricing, rate limits, model quality, deprecation timelines.

---

## 3. External stakeholders (regulators & ecosystem)

### 3.1 Regulator — RBI (Reserve Bank of India)
**Role:** Sets rules for digital payment safety, tokenization, fraud disclosure, customer grievance redressal.
**Why they care:** Digital fraud is a national-priority issue in India; the RBI has issued multiple 2024–2026 advisories on AI-agent and card-on-file safety.
**What we provide:** Full audit trail, deterministic policy, real-time risk scores, evidence-backed decisions — all auditable.
**What we DON'T do:** No offensive action; no card-data storage; no money movement ourselves.

### 3.2 Regulator — SEBI / IRDAI
**Role:** For merchants in securities/insurance, additional rules apply (e.g., mis-selling).
**Why they care:** AI agents making investment or insurance purchases on behalf of users need the same "suitability check" the user would do.
**What we provide:** The `category_blocked` policy mechanism (e.g., "block `derivatives, complex_insurance` unless approved by qualified advisor").

### 3.3 Industry bodies
- **PCI-DSS:** We don't touch card data; we only authorize / ask / deny. This minimizes our PCI scope.
- **NPCI (UPI):** Indirectly relevant for Indian UPI flows. We plug into UPI via PSPs, not directly.
- **NASSCOM / iSPIRT:** Industry associations for product feedback and policy advocacy.

### 3.4 Auditors (SOC 2, ISO 27001)
**Why they care:** Enterprise customers will demand third-party security audits before deploying.
**What we provide:** Audit log, deterministic decisions, encryption at rest/transit, access controls, secret rotation.

---

## 4. Internal stakeholders (the team)

### 4.1 Engineering
**Goal:** Build a reliable, scalable, secure system.
**Pain points to avoid:** Flaky AI providers (solved by fallback chain), LLM hallucination (solved by fact-bound prompts), hidden coupling (solved by layered architecture).

### 4.2 Product
**Goal:** Discover the right policies, scoring dimensions, and counterfactual cost model that resonate with merchants.
**Method:** Talk to 5–10 merchants in Y1, run A/B tests on policy templates, measure precision/recall impact.

### 4.3 Sales / GTM
**Goal:** Land 10–50 design-partner merchants in Y1, expand to 500+ paying by Y3.
**Method:** PSP partnership, AI-agent platform listings, content marketing (Fraud Friday newsletter, buildathon talks).

### 4.4 Compliance / Legal
**Goal:** Stay ahead of AI-payment regulation; clear privacy policy; vendor contracts.
**Method:** Quarterly compliance review; privacy-by-design; data minimization.

### 4.5 Customer Success
**Goal:** Onboard new merchants in < 7 days; reduce churn to < 5% annually.
**Method:** Self-serve onboarding; "policy templates" library (e.g., "e-commerce starter policy", "B2B SaaS policy").

---

## 5. Stakeholder map (power × interest grid)

```
                  High power
                      |
   [Regulators]       |       [Payment Service Providers]
   [Cloud providers]  |       [AI Agent Platforms]
                      |
   Low interest <-----+-----> High interest
                      |
   [End Users]        |       [Merchants]  ← primary GTM focus
   [Auditors]         |       [Risk Ops]
                      |
                  Low power
```

**GTM priorities (in order):**
1. **Merchants** (primary customers — high interest, moderate power)
2. **PSP partnerships** (channel — high power, high interest)
3. **AI agent platforms** (long-term distribution — high power, building interest)
4. **Regulators** (compliance — high power, low interest; we engage proactively)
5. **End users** (indirect — we win them by serving merchants well)

**Need:** Visibility into why a decision was made; ability to override; forensic audit.
**How they use it:** Audit Log, AI Investigation page, Decision Simulator.
**Success metric:** Time to investigate a flagged decision < 5 minutes; override accuracy > 95%.
