# Use Cases — PayTrust AI

> Detailed use-case catalogue. 8 use cases covering the full lifecycle of a payment decision.
> Format: **UC-NN · Title · Primary actor · Status**

---

## UC-01 · First-time user agent policy creation

**Actor:** Merchant ops team
**Goal:** Define what an AI agent is allowed to do on behalf of a user.
**Status:** ✅ Implemented (Agent Policy page)

**Preconditions:**
- Merchant has a verified PayTrust AI account
- At least one user and one AI agent exist in the system

**Main flow:**
1. Ops navigates to **Agent Policy**
2. Selects a user (e.g., "Test User") and agent (e.g., "Shopping Assistant")
3. Sets `daily_limit` (e.g., ₹100,000) — total spend the agent may do in 24h
4. Sets `max_transaction` (e.g., ₹60,000) — single-payment ceiling
5. Sets `approval_threshold` (e.g., ₹30,000) — payments above this trigger human approval
6. Enters allowed categories (e.g., `electronics, books, travel`)
7. Enters blocked categories (e.g., `gambling, financial_products`)
8. Clicks **Save Policy**
9. System persists the policy in `agent_policies` table
10. System returns success and shows the saved policy

**Postconditions:**
- The new policy is in effect immediately for subsequent payment requests
- An audit-log entry is written (`actor=ops, action=policy.update`)

**Exception flow:**
- Invalid input (e.g., `approval_threshold > max_transaction`): form rejects submission with explanation
- Concurrent edit by another ops user: last-write-wins with audit log of both writers

---

## UC-02 · Legitimate payment request → ALLOW

**Actor:** AI agent (e.g., Shopping Assistant)
**Goal:** Make a small, policy-compliant payment.
**Status:** ✅ Implemented (Payment Request page)

**Preconditions:**
- Active policy exists for this user+agent pair
- Payment request is well-formed (Pydantic validation)

**Main flow:**
1. Agent submits `POST /v1/evaluate` (or uses the Streamlit form):
   - `amount=₹25,000`, `category=electronics`, `merchant_name=Croma`, `user_id=1`, `agent_id=1`
2. **PolicyEngine** evaluates: `daily_spent=0 < 100k`, `25k < 60k max`, `25k < 30k approval`, `electronics ∈ allowed`, `electronics ∉ blocked` → `authorized=True, requires_approval=False`
3. **RiskEngine** assesses: amount in normal range, no violations, no velocity, no new device → `risk_score=15 (LOW)`, 2 low-severity factors
4. **DecisionEngine** decides: no policy violation, risk is LOW → **ALLOW**
5. **DecisionSimulator** computes counterfactuals: ALLOW ₹0, ASK ₹285, DENY ₹418 — confirms ALLOW cheapest for low-risk legit
6. Decision is persisted with `request_id` and audit log entry
7. Response returned to agent: `{decision: "ALLOW", risk_score: 15, factors: [...], counterfactuals: [...]}`
8. Agent proceeds with Razorpay payment (Test Mode)

**Postconditions:**
- `payment_requests` row created, `audit_logs` entry written
---

## UC-03 · Mid-size payment → ASK_USER (human approval)

**Actor:** AI agent
**Goal:** Make a payment that requires explicit user consent.
**Status:** ✅ Implemented (Payment Request page)

**Main flow:**
1. Agent submits payment `amount=₹35,000`, `category=travel`, `merchant=MakeMyTrip`
2. **PolicyEngine** runs: `35k < 100k daily`, `35k < 60k max`, **`35k > 30k approval threshold`** → `authorized=True, requires_approval=True`
3. **RiskEngine** runs: travel not blocked, normal amount → `risk_score=22 (LOW)`
4. **DecisionEngine**: policy requires approval → **ASK_USER**
5. **DecisionSimulator** shows: ASK_USER cheapest in this scenario (avoid fraud exposure if it's fraud, accept friction cost for legit)
6. Response: `{decision: "ASK_USER", requires_approval: true, approval_url: "..."}`

**Postconditions:**
- The agent presents a consent dialog to the user
- User taps "Approve" or "Reject"
- A subsequent call (`POST /v1/evaluate` with `user_approved=true/false`) re-evaluates and finalizes
- If approved: ALLOW. If rejected: DENY.

---

## UC-04 · Payment that violates policy → DENY

**Actor:** AI agent
**Goal:** Attempt a payment in a blocked category.
**Status:** ✅ Implemented

**Main flow:**
1. Agent submits `amount=₹10,000`, `category=gambling`
2. **PolicyEngine** runs: `10k < 60k max`, `10k < 30k approval` → BUT `gambling ∈ blocked` → **`authorized=False, violations=[category_blocked]`**
3. **RiskEngine** adds high-severity factor `policy_violation: category_blocked`
4. **DecisionEngine**: hard policy violation → **DENY** (no LLM can override this)
5. **DecisionSimulator**: even ALLOW would have policy violation, so ALLOW is suppressed; recommended = DENY
6. Response: `{decision: "DENY", violations: ["category_blocked"]}`

**Postconditions:**
- Agent MUST NOT submit the payment to Razorpay
- Audit log captures the violation and the deny reason

---

## UC-05 · Large payment that exceeds max → DENY

**Actor:** AI agent
**Goal:** Attempt a payment larger than the per-transaction cap.
**Status:** ✅ Implemented

**Main flow:**
1. Agent submits `amount=₹65,000`, `category=electronics`
2. **PolicyEngine** runs: **`65k > 60k max`** → `authorized=False, violations=[max_transaction_exceeded]`
3. **DecisionEngine** → **DENY**
4. Response: `{decision: "DENY", violations: ["max_transaction_exceeded"]}`

---

## UC-06 · AI Investigation of a flagged decision

**Actor:** Human analyst (risk team)
**Goal:** Understand why a transaction was flagged.
**Status:** ✅ Implemented (AI Investigation page)

**Main flow:**
1. Analyst opens **AI Investigation** page
2. Selects a past decision (e.g., a DENY with risk 75)
3. Clicks **Investigate**
4. **AIEngine** calls OpenRouter → Groq → Gemini → deterministic fallback
5. Each provider receives ONLY structured facts (no PII, no raw text invention)
6. Provider returns: `explanation`, `summary`, `concerns[]`, `review_questions[]`, `confidence`
7. UI displays explanation in an info card, concerns & review questions in bordered columns
8. Confidence shown as a progress bar (0–100%)
9. Full JSON in expandable disclosure

**Failure recovery:**
- All providers fail → deterministic fallback (always succeeds) explains in template form
- Confidence < 0.5 → displayed as a "low confidence" warning, but the deterministic decision is unchanged

---

## UC-07 · Counterfactual decision comparison

**Actor:** Risk team / ops
**Goal:** Understand the economic trade-off between ALLOW / ASK_USER / DENY.
**Status:** ✅ Implemented (Decision Simulator + Evaluation page)

**Main flow:**
1. Analyst selects a transaction
2. Views 3 bordered cards: **What if ALLOW?** / **What if ASK_USER?** / **What if DENY?**
3. Each card shows: `fraud_exposure`, `false_positive_cost`, `operational_cost`, `customer_friction`, `expected_total_cost`
4. SIMULATED label is prominently displayed — these are model assumptions, not real money
5. Recommended action = minimum expected cost subject to hard policy guards

**Use case:** "If we DENY this, we lose ₹1,500 in customer friction but save ₹50,000 in fraud exposure. Net: ALLOW is the right call."

---

## UC-08 · Held-out evaluation against real fraud data

**Actor:** Data scientist / judge
**Goal:** Measure true generalization of the ML model.
**Status:** ✅ Implemented (`python evaluation/run_evaluation.py`)

**Main flow:**
1. Run `python evaluation/run_evaluation.py`
2. Loads `evaluation/ieee_test_predictions.parquet` (3,000 temporal rows, never seen during training)
3. Computes precision, recall, F1, FPR, FNR, confusion matrix, PR-AUC, ROC-AUC
4. Runs a 19-point threshold sweep with SIMULATED cost model
5. Writes `evaluation/results.json` (machine-readable) + `evaluation/report.md` (human-readable)
6. Both committed to repo — no hand-curated numbers anywhere

**Honest result:**
- PR-AUC 0.3145, ROC-AUC 0.8419 (real, not tuned for marketing)
- Max F1: 0.30 @ p≈0.95
- Min SIM cost: at p=1.0 (block nothing) — illustrates the cost model
- Synthetic-data 1.0 numbers are explicitly disclaimed

---

## Use-case coverage matrix

| | UC-01 | UC-02 | UC-03 | UC-04 | UC-05 | UC-06 | UC-07 | UC-08 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| PolicyEngine | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | — |
| RiskEngine | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — |
| DecisionEngine | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — |
| DecisionSimulator | — | ✅ | ✅ | ✅ | ✅ | — | ✅ | — |
| AIEngine | — | — | — | — | — | ✅ | — | — |
| Razorpay integration | — | ✅ | ✅ | — | — | — | — | — |
| ML evaluation | — | — | — | — | — | — | — | ✅ |
| Audit trail | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

All 8 use cases are implemented and demonstrable in the live dashboard.

- Agent can submit the payment to Razorpay

**Performance:** end-to-end P50 < 50ms, P95 < 200ms (no LLM call)
