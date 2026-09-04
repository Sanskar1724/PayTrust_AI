# Glossary — PayTrust AI

> Domain terms, abbreviations, and project-specific definitions.

## Decisions & policy

| Term | Definition |
|---|---|
| **ALLOW** | Deterministic approval — payment proceeds without human touch |
| **ASK_USER** | Human-in-the-loop: amount/behavior crossed `approval_threshold`; recorded in `approvals` |
| **DENY** | Blocked by policy violation or critical risk; reason codes always attached |
| **Policy is law** | PolicyEngine output is binding; no other component (incl. LLM) can override it |
| **daily_limit** | Policy cap on summed same-day approved spend per user/agent |
| **max_transaction** | Policy cap per single transaction |
| **approval_threshold** | Amount above which ASK_USER is forced |
| **blocked_categories** | Hard-deny merchant categories (e.g., gambling, financial_products) |
| **Defense-only** | Product principle: authorize/ask/deny only — never offensive actions |

## Risk & ML

| Term | Definition |
|---|---|
| **Risk score (0–100)** | Weighted 7-dimension score from `RiskEngine`; banded LOW <30 ≤ MEDIUM <60 ≤ HIGH <80 ≤ CRITICAL |
| **Risk factors** | Named evidence lines (e.g., `amount_risk`, `spending_behavior`) with severity + details |
| **PR-AUC** | Precision-Recall Area Under Curve — headline metric for imbalanced fraud data |
| **IEEE-CIS** | Real fraud dataset (590k tx, ~3.5% fraud) used for held-out calibration |
| **Temporal split** | Train/test split by time — no future leakage into training |
| **Held-out** | Test rows the model never saw; all quoted metrics come from here |
| **Threshold tool** | UI/REST picker over 3,000 real held-out rows showing precision/recall/F1/FPR vs cost |

## AI advisory tier

| Term | Definition |
|---|---|
| **Advisory-only LLM** | Explains the decision; never changes it — enforced by architecture |
| **Fallback chain** | OpenRouter → Groq → Gemini → deterministic provider |
| **Deterministic provider** | Rule-based explanation generator; guarantees offline function |
| **Circuit breaker** | Per-provider: 5 consecutive failures → skip provider for 60 s |
| **`fallback_used`** | Response flag: true when the primary provider wasn't the responder |
| **Fact-bound prompt** | LLM receives structured facts only (no PII); forbidden to invent numbers |
| **review_questions** | LLM-suggested analyst questions in the `ai` block |

## Simulation & costs

| Term | Definition |
|---|---|
| **Counterfactuals** | Simulated ALLOW/ASK_USER/DENY alternatives for the same transaction |
| **SIMULATED / ESTIMATED** | Label everywhere model-assumed values appear — never real measurements |
| **False-positive cost (FP)** | Friction + support + merchant impact of wrongly blocking legit users |
| **Fraud exposure (FN)** | Expected loss if a fraud is allowed through |
| **Expected total cost** | FP + FN + operational cost per counterfactual; minimization target |

## Platform & ops

| Term | Definition |
|---|---|
| **request_id** | Global correlation key across payments, decisions, risk, audit |
| **Audit log** | Append-only event ledger (`audit_logs`) — no updates, no deletes |
| **Idempotency** | Same `request_id`/`event_id` replays stored result, no side effects |
| **DLQ** | Dead-letter queue: webhook deliveries that exhausted retries (`razorpay_events`) |
| **HMAC verification** | SHA-256 signature over the raw webhook body before any processing |
| **Test-mode enforcement** | Only `rzp_test_*` Razorpay keys accepted; live keys refused in code |
| **CORS allowlist** | `CORS_ALLOW_ORIGINS` — `*` in dev only, explicit list in production |
| **WAL** | Write-Ahead Logging (SQLite) — concurrent reads during writes |
| **`/ready`** | Readiness probe: DB + model artifacts present before serving traffic |

## Money & format

| Term | Definition |
|---|---|
| **INR amounts** | Transaction currency in examples; policy limits are INR |
| **processing_ms** | Server-measured decision latency (deterministic path ≈ 15 ms) |
| **BUILDATHON** | Razorpay Buildathon Track 02 — AI Risk Manager (project context) |
