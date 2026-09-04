# PayTrust AI — Project Documentation

> **PayTrust AI — Evidence-Driven Payment Risk & Loss Prevention**
> Razorpay Buildathon · Track 02 — AI Risk Manager
> Last updated: 2026-09-02

Welcome to the PayTrust AI documentation suite. This is the single source of truth
for what the product is, who uses it, how it works, how it scales, and how much it costs.

---

## Table of contents

### Business documentation ([business/](business/))
| Document | Audience | Purpose |
|---|---|---|
| [USE_CASES.md](business/USE_CASES.md) | Product, Sales, Judges | 8 detailed use cases with actors, preconditions, flows, postconditions |
| [STAKEHOLDERS.md](business/STAKEHOLDERS.md) | PM, Exec | Stakeholder map (merchants, agents, ops, auditors, regulators) |
| [BUSINESS_MODEL.md](business/BUSINESS_MODEL.md) | Investors, Exec | Revenue model, pricing tiers, unit economics, GTM |
| [MARKET_ANALYSIS.md](business/MARKET_ANALYSIS.md) | Investors, Strategy | TAM/SAM/SOM, competitors, positioning, trends |

### Technical documentation ([technical/](technical/))
| Document | Audience | Purpose |
|---|---|---|
| [SRS.md](technical/SRS.md) | Engineering | Software Requirements Specification (functional + non-functional) |
| [ARCHITECTURE.md](technical/ARCHITECTURE.md) | Engineering | System architecture, component map, data flow diagrams |
| [FUNCTIONAL_REQ.md](technical/FUNCTIONAL_REQ.md) | Engineering | FR-1…FR-11 detailed functional requirements, prioritized (MoSCoW) |
| [NON_FUNCTIONAL_REQ.md](technical/NON_FUNCTIONAL_REQ.md) | Engineering, SRE | NFR-1…NFR-12: performance, reliability, security, scalability, observability |
| [API_REFERENCE.md](technical/API_REFERENCE.md) | Integrators | REST API reference — all 9 endpoints, real schemas, error codes |
| [DATA_MODEL.md](technical/DATA_MODEL.md) | Engineering | SQLite schema, 10 tables, ERD, indexes, retention |
| [SECURITY.md](technical/SECURITY.md) | Security, Compliance | Threat model, controls, audit trail, secrets handling |
| [SCALABILITY.md](technical/SCALABILITY.md) | SRE, Architects | Bottlenecks, scaling path, capacity planning |
| [DEPLOYMENT.md](technical/DEPLOYMENT.md) | DevOps | Local, Docker, compose, HF Spaces; env var matrix |
| [SERVICE_PROVIDERS.md](technical/SERVICE_PROVIDERS.md) | Procurement | Vendor evaluations: payments, LLM, data, cloud, observability |
| [INTEGRATIONS.md](technical/INTEGRATIONS.md) | Engineering | Razorpay, webhooks, OpenRouter, IEEE-CIS dataset |
| [COST_ESTIMATION.md](technical/COST_ESTIMATION.md) | Finance, Exec | Infra cost projections at 1k / 10k / 100k / 1M tx/day |
| [DISASTER_RECOVERY.md](technical/DISASTER_RECOVERY.md) | SRE, Compliance | RTO/RPO, backup, failover, runbook |
| [GLOSSARY.md](technical/GLOSSARY.md) | Everyone | Domain terms, abbreviations, definitions |
| [PRACTICAL_WALKTHROUGH.md](technical/PRACTICAL_WALKTHROUGH.md) | Everyone, Judges | Every feature with real expected responses (live-captured) |
| [CONNECTIVITY_AND_OPENROUTER_CHECK.md](technical/CONNECTIVITY_AND_OPENROUTER_CHECK.md) | Everyone | Live backend/frontend/OpenRouter connectivity + evaluation verdict |

### Existing documentation (preserved, docs root)
- [AI_ENGINE.md](AI_ENGINE.md) — AI provider abstraction, prompt, fact-bound design
- [API.md](API.md) — Quick API reference (formal expansion: [technical/API_REFERENCE.md](technical/API_REFERENCE.md))
- [ARCHITECTURE.md](ARCHITECTURE.md) — Diagram-focused view (formal expansion: [technical/ARCHITECTURE.md](technical/ARCHITECTURE.md))
- [DECISION_ENGINE.md](DECISION_ENGINE.md) — How ALLOW/ASK_USER/DENY is chosen
- [DEMO.md](DEMO.md) — Judge-facing demo script
- [DEPLOYMENT.md](DEPLOYMENT.md) — Local deployment quickstart (formal expansion: [technical/DEPLOYMENT.md](technical/DEPLOYMENT.md))
- [OBSERVABILITY.md](OBSERVABILITY.md) — Logs, metrics, traces
- [ROADMAP.md](ROADMAP.md) — 4-phase plan + 15 buildathon requirements checklist
- [SECURITY.md](SECURITY.md) — Security checklist (formal expansion: [technical/SECURITY.md](technical/SECURITY.md))
- [TESTING.md](TESTING.md) — Test strategy

### Generated artifacts (regenerable, repo root)
- [FINAL_STATUS.md](../FINAL_STATUS.md) — Status report (all numbers from actual runs)
- [evaluation/results.json](../evaluation/results.json) — Last evaluation results
- [evaluation/report.md](../evaluation/report.md) — Human-readable report
---

## What is PayTrust AI?

**One-line positioning:**
> PayTrust AI doesn't just detect risky payments — it helps merchants make safer, evidence-based, and economically justified decisions while protecting legitimate customers.

**The product, in three sentences:**

PayTrust AI is an **AI-agent payment safety layer** that sits between a user's AI
agent (e.g., a Shopping Assistant) and a payment infrastructure (e.g., Razorpay).
For every payment the agent wants to make, PayTrust AI runs a deterministic policy
check, a risk-scoring engine, an advisory AI investigation, and a counterfactual
cost simulation to recommend one of three actions: **ALLOW** (let it through),
**ASK_USER** (require human approval), or **DENY** (block). Every decision is
evidence-backed, logged immutably, and explainable.

**Key differentiators**

| Capability | Why it matters |
|---|---|
| **Deterministic policy engine** | Policy is law — no LLM can override hard rules |
| **Evidence-based risk scoring** | 7 dimensions, calibrated on IEEE-CIS (PR-AUC 0.314 held-out) |
| **Counterfactual simulator** | Simulates ALLOW/ASK_USER/DENY costs in real time |
| **Audit trail** | Every decision, immutable, request_id-traceable |
| **Payment integration** | Razorpay Test Mode (HMAC, idempotent, DLQ) |
| **Deployment** | Streamlit + SQLite (local) · FastAPI + Postgres + Redis (production) |

---

## Quick links for different readers

- **Judges / first-time viewers** → start with [business/USE_CASES.md](business/USE_CASES.md), then [technical/PRACTICAL_WALKTHROUGH.md](technical/PRACTICAL_WALKTHROUGH.md), then the live demo at http://localhost:8501 (after `streamlit run app.py`)
- **Investors / business** → [business/MARKET_ANALYSIS.md](business/MARKET_ANALYSIS.md) and [business/BUSINESS_MODEL.md](business/BUSINESS_MODEL.md)
- **Engineers integrating** → [technical/API_REFERENCE.md](technical/API_REFERENCE.md), then [technical/INTEGRATIONS.md](technical/INTEGRATIONS.md)
- **Security/compliance reviewers** → [technical/SECURITY.md](technical/SECURITY.md), [technical/NON_FUNCTIONAL_REQ.md](technical/NON_FUNCTIONAL_REQ.md)
- **DevOps/SRE** → [technical/DEPLOYMENT.md](technical/DEPLOYMENT.md), [technical/SCALABILITY.md](technical/SCALABILITY.md), [technical/DISASTER_RECOVERY.md](technical/DISASTER_RECOVERY.md)
- **Procurement/finance** → [technical/SERVICE_PROVIDERS.md](technical/SERVICE_PROVIDERS.md), [technical/COST_ESTIMATION.md](technical/COST_ESTIMATION.md)

---

## Documentation conventions

- **ALL CAPS words** in the UI (ALLOW, ASK_USER, DENY) are decision types.
- "SIMULATED" / "ESTIMATED" labels mean the value is a model assumption, not a real-world measurement.
- "held-out test" means a temporal split the model never saw during training — true generalization numbers.
- PR-AUC (not accuracy) is the right headline metric for fraud detection (3.5% positive class).
- All numbers in this suite come from `python evaluation/run_evaluation.py` (real, reproducible).
- "Defense-only" means we never perform offensive actions (no fraud rings, no account takeovers, no botnets). We only authorize, ask, or deny.

---

## Maintained by

PayTrust AI engineering · Sanskar Singh · Buildathon 2026
For questions, see [FINAL_STATUS.md](../FINAL_STATUS.md) or open an issue.