# Market Analysis — PayTrust AI

> Market size, segmentation, competition, and strategic positioning.

---

## 1. The agentic-commerce opportunity

The number of AI agents capable of making purchases on behalf of users is growing
exponentially. As of 2026:

- **OpenAI Operator** (and Apps SDK) is GA
- **Anthropic Claude with Computer Use** is GA and gaining MCP-tool support
- **Google Gemini** has agentic capabilities in Workspace
- **Microsoft Copilot** can transact in Teams + commerce integrations
- **Vertical agents**: shopping (e.g., Amazon Rufus actions), travel (e.g., Booking.com AI), B2B SaaS (e.g., Salesforce Agentforce)

**Key insight:** Every one of these agents will eventually need a "permission layer" —
who decides what the agent is allowed to do, and how do you stop a runaway agent from
draining a user's account? PayTrust AI is that layer.

---

## 2. Market size (TAM / SAM / SOM)

### 2.1 Total Addressable Market (TAM)

**Global payment fraud detection & prevention market:**
- 2024: USD 40 billion
- 2030 (projected): USD 100+ billion (CAGR ~16%)
- Sources: Mordor Intelligence, Grand View Research, MarketsandMarkets

**Of which, AI-agent-specific authorization:**
- Currently a sub-segment (< USD 1B) but fastest-growing
- By 2030, expected to be USD 5–10B as agentic commerce matures

---

## 3. Customer segmentation

### 3.1 By size
| Segment | Definition | Count in target markets | Avg fraud budget / yr |
|---|---|---|---|
| **SMB** | < 100 employees, < $5M revenue | 100,000+ | $1k–$10k |
| **Mid-market** | 100–1,000 employees, $5M–$100M | 30,000 | $10k–$100k |
| **Enterprise** | 1,000+ employees, $100M+ | 5,000 | $100k–$1M+ |

### 3.2 By use case
- **D2C e-commerce** (Shopify, WooCommerce, custom) — highest fraud exposure, biggest pain
- **B2B SaaS billing** (Stripe-billed SaaS) — moderate fraud, high contract value
- **Marketplace / P2P** (Etsy, eBay, OLX) — counterparty risk
- **Travel & hospitality** (Booking, MakeMyTrip) — high-value transactions, high chargeback cost
- **Subscription services** — friendly-fraud (customers disputing legitimate charges)

### 3.3 By AI agent maturity
- **Today (2026):** < 1% of merchants have AI agents transacting. **Land grab phase.**
- **By 2028:** 10–20% of merchants will have at least one agent.
- **By 2030:** Majority of consumer transactions may involve an agent.

---

## 4. Competitive landscape

### 4.1 Direct competitors
| Company | Focus | Funding | Strength | Weakness |
|---|---|---|---|---|
| **Sift** | Trust & safety (content + payments) | $100M+ | Brand, scale | Legacy UX, not AI-native |
| **Kount** (Equifax) | Fraud prevention | Acquired | Equifax data | Built pre-agentic era |
| **Forter** | E-commerce fraud | $200M+ | Real-time decisions | Expensive, opaque |
| **Signifyd** | Chargeback guarantee | $400M+ | Money-back guarantee | Focused on chargebacks, not agentic |
| **Ravelin** | UK/EU fraud | $30M+ | ML quality | Limited markets |
| **Sardine** | AI fraud (US) | $70M+ | AI-native | US-only, no agentic focus |
| **Riskified** | E-commerce chargebacks | Public (NYSE) | Scale | Expensive |

---

## 5. Market trends (2026–2030)

### 5.1 Tailwinds
- **Regulatory pressure** on AI agents (RBI, EU AI Act, US state laws) — increases need for a third-party safety layer
- **AI agent adoption** growing 3–5× annually through 2028
- **Chargeback costs** rising (US: $100+ per dispute; India: ₹100–500 per dispute)
- **Customer trust** decreasing in card-not-present transactions
- **PSP partnerships** becoming the dominant B2B SaaS distribution model

### 5.2 Headwinds
- **Big-tech bundling** (Stripe Radar for free with Stripe, Adyen Protect free with Adyen)
- **Open-source ML** reducing moat (every fraud team can build their own model)
- **Regulatory fragmentation** (India vs EU vs US rules differ)
- **False-positive backlash** (merchants want to sell, not block)

### 5.3 Our response
- Stay **provider-neutral** (multi-PSP support)
- **Counterfactual engine** is hard to replicate (unique IP)
- **Evidence UX** reduces false-positive complaints (merchants see why)
- **Buildathon-grade polish** (this codebase) signals engineering quality

---

## 6. Strategic positioning

### 6.1 Beachhead strategy
**Year 1 focus:** 25 design partners in India + US, mostly D2C e-commerce and travel.
- High fraud exposure
- Fast to integrate
- High willingness to pay

**Why India first?**
- Razorpay integration is the buildathon's gift — we have a working integration
- Indian merchants have a strong cost-sensitivity (good fit for usage-based pricing)
- RBI's pro-innovation stance on AI agents gives us regulatory tailwind

### 6.2 Expansion strategy
**Year 2:** Southeast Asia (Singapore, Indonesia, Philippines) — fast-growing, English-speaking
**Year 3:** US and EU — bigger TAM, more competition
**Year 5:** Global; verticals: SaaS billing, B2B procurement, insurance

### 6.3 Defensibility strategy
- **Network effects:** Each merchant's blocked fraud trains the model for all merchants (with privacy)
- **Counterfactual engine:** Patent-pending; hard to replicate
- **AI-agent platform listings:** Distribution moat once we're in the "app store"
- **Brand:** "The safe way to spend with AI agents" — first-mover in a growing category

---

## 7. Key risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Razorpay builds in-house competitor | High | High | Be multi-PSP; partner with Stripe/Adyen too |
| Regulators ban AI agents | Low | Fatal | We make AI agents safer, not less safe — they're a beneficiary |
| Fraud ML commoditizes (OSS) | Medium | Medium | Differentiate on UX + counterfactual, not just ML |
| PSP drops us for compliance | Low | High | Be the audit-log that the regulator wants to see |
| Slow AI agent adoption | Medium | High | Build horizontal tools (policy engine, decision simulator) for non-agent cases too |

---

## 8. What we are NOT

To be clear about positioning:
- ❌ We are NOT a chargeback-guarantee product (signifyd's space)
- ❌ We are NOT a content-trust-and-safety product (Sift's adjacent space)
- ❌ We are NOT a card-network fraud product (Visa/Mastercard)
- ❌ We are NOT a payment processor (Razorpay, Stripe, etc.)
- ❌ We are NOT an offensive fraud-investigation tool (we never attack fraudsters)

**We ARE the safety layer for AI-agent payments.** The third party that says "this payment is safe" or "this payment needs human approval" or "this payment is too risky — block it."

### 4.2 Indirect competitors
- **PSPs building in-house** (Razorpay, Stripe Radar, Adyen Protect)
- **Card networks** (Visa VAA, Mastercard Decision Intelligence)
- **In-house engineering** at large merchants

### 4.3 The PayTrust AI position

```
                    AI-native
                       ^
                       |
            PayTrust AI|
              ●        |
            Sardine    |   Razorpay Risk
                       |
   Legacy ◄----------- + ----------► In-house
                       |
            Sift       |    Forter
            Kount      |    Signifyd
            Ravelin    |    Riskified
                       |
                       v
                   Legacy / human-driven
```

**Position:** AI-native + agentic-commerce specialized + counterfactual engine + evidence-driven UX. We're the only company in the upper-right quadrant that also has a counterfactual engine.

### 2.2 Serviceable Addressable Market (SAM)

**Focus regions:** India, Southeast Asia, US, EU, UK
**Focus segments:** E-commerce, SaaS billing, travel, marketplaces, B2B procurement

| Region | 2026 fraud spend | % of global | SAM (PayTrust share) |
|---|---|---|---|
| India | USD 3B | 7% | USD 100M |
| Southeast Asia | USD 5B | 12% | USD 200M |
| US | USD 18B | 45% | USD 800M |
| EU + UK | USD 8B | 20% | USD 400M |
| **Total SAM** | — | — | **USD 1.5B** |

### 2.3 Serviceable Obtainable Market (SOM) — 3-year realistic

| Year | Paying customers | ARPU | ARR | % of SAM |
|---|---|---|---|---|
| Y1 (2026) | 25 | USD 360 | **USD 0.1M** | < 0.01% |
| Y2 (2027) | 200 | USD 480 | **USD 1.2M** | 0.08% |
| Y3 (2028) | 1,000 | USD 600 | **USD 7.2M** | 0.5% |
| Y5 (2030) | 10,000 | USD 720 | **USD 86M** | 5.7% |

**Penetrating 5% of SAM in 5 years is realistic for a focused startup.**
