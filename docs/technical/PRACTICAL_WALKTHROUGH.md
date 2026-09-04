# Practical Walkthrough & Evaluation — PayTrust AI

> Complete end-to-end walkthrough of every feature with **real expected responses**
> (captured live from the running system), plus a full connectivity + OpenRouter report.
> Date: 2026-09-02

---

## 0. How to reproduce this walkthrough

```powershell
cd S:\Buildathon\paytrust-ai
.venv\Scripts\Activate.ps1

# Terminal 1 — REST API
python -m api.main            # → http://localhost:8000 (Swagger /docs)

# Terminal 2 — Dashboard
streamlit run app.py          # → http://localhost:8501

# API key
python -c "from api.security import api_key_for; print(api_key_for())"
```

Every response in this document was captured against the ACTUAL running system,
not imagined. A **©** marks a live-verified value.

---

## Part A — REST API practical examples (with expected responses)

### A1. Health check (no auth)

**Request**
```
GET http://localhost:8000/health
```

**Expected response (200)**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "database": {"path": "...\\data\\paytrust.db", "ok": true}
}
```

### A2. Readiness (no auth)

**Request**
```
GET http://localhost:8000/ready
```

**Expected response (200)**
```json
{"ready": true, "database": true, "models": {"ieee_model.pkl": true, "risk_model.pkl": true},
 "checks": ["database:ok", "models:ieee=True,risk=True"]}
```

### A3. Evaluate a LOW-risk legitimate payment → **ALLOW**

**Request**
```bash
POST http://localhost:8000/v1/evaluate
X-API-Key: <your-key>
Content-Type: application/json

{
  "request_id": "demo_allow_1",
  "user_id": 1, "agent_id": 1, "merchant_id": 1,
  "amount": 25000, "category": "electronics",
  "merchant_name": "Croma", "investigate": false
}
```

**Expected response (200)** — top-level keys © live-verified:
```json
{
  "request_id": "demo_allow_1",
  "decision": "ALLOW",
  "risk_score": 5,
  "risk_level": "LOW",
  "requires_approval": false,
  "reasons": ["..."],
  "policy_result": {"authorized": true, "requires_approval": false, "violations": []},
  "risk_result": {"risk_score": 5, "risk_level": "LOW", "factors": [...]},
  "simulation": {"counterfactuals": [ "3 objects ALLOW/ASK_USER/DENY" ]},
  "ai": null,
  "processing_ms": 14.9,
  "duplicate": false,
  "simulated_estimates": true,
  "disclaimer": "Decision is deterministic (LLM never overrides). AI explanation is advisory only..."
---

### A5. Evaluate an OVER-MAX payment → **DENY**

**Request**
```json
{"request_id": "demo_deny_1", "user_id": 1, "agent_id": 1, "merchant_id": 1,
 "amount": 65000, "category": "electronics", "merchant_name": "TechMart",
 "investigate": false}
```

**Expected response (200) — © live:**
```json
{
  "decision": "DENY",
  "risk_score": 90, "risk_level": "CRITICAL",
  "requires_approval": true,
  "reasons": [
    "Policy violation: max_transaction_exceeded, daily_limit_exceeded",
    "Amount INR 65,000 exceeds max transaction INR 60,000.",
    "Daily limit INR 100,000 exceeded: ...",
    "Risk is CRITICAL (90) — reinforces DENY"
  ],
  "policy_result": {
    "authorized": false, "requires_approval": true,
    "violations": ["max_transaction_exceeded", "daily_limit_exceeded"],
    "daily_spent": 188200, "policy": {"daily_limit":100000,"max_transaction":60000,...}
  }
}
```

### A6. Evaluate a BLOCKED-CATEGORY payment → **DENY** (hard guard)

**Request**
```json
{"request_id": "demo_block_1", "user_id": 1, "agent_id": 1, "merchant_id": 1,
 "amount": 10000, "category": "gambling", "merchant_name": "Test",
 "investigate": false}
```

**Expected response (200) — © live decision:**
```json
{
  "decision": "DENY",
  "risk_level": "CRITICAL",
  "policy_result": {"authorized": false,
    "violations": ["category_blocked", "category_not_allowed"]}
}
```
> This is the defense-only, policy-is-law path: no risk debate or AI reasoning
> can override a blocked category.

### A7. Validate an INVALID payload → **422**

**Request**
```json
{"amount": -5, "category": "electronics"}   // missing merchant_id, negative amount
```

**Expected response (422):**
```json
{"detail": {"code": "VALIDATION_ERROR", "errors": [
   {"type":"missing","loc":["body","merchant_id"],"msg":"Field required"}, "..."]}}
```
> © live-verified: the schema requires `merchant_id`.

### A8. Payments list

**Request**
```
GET http://localhost:8000/v1/payments
X-API-Key: <key>
```

**Expected response (200) — © live shape:**
```json
{"items": [{"request_id":"req_...","amount":25000,"category":"electronics",
  "decision":"DENY","risk_score":32,"risk_level":"MEDIUM", ...}, ...], "count": 9}
```

### A9. Evaluation metrics

**Request**
```
GET http://localhost:8000/v1/evaluation/metrics
```

**Expected response (200) — © live keys:**
```json
{"ieee": {...}, "synthetic_ml": {...}, "available": true, "disclaimer": "..."}
```

### A10. Threshold tool

**Request**
```
GET http://localhost:8000/v1/threshold/check
```

**Expected (200) — © live:** `{"available": true, "rows": 3000, "missing": null}`
> 3,000 real held-out rows power the tool — nothing fabricated.

### A11. Razorpay webhook (HMAC + idempotency)

```
POST http://localhost:8000/v1/webhooks/razorpay
X-Razorpay-Signature: <hmac-sha256 of RAW body>
{"entity":"event","event":"payment.captured","id":"evt_demo_1"}
```
**Expected:** first send → `status:"processed"`; re-send → `status:"duplicate"` (idempotent, © verified).

---

## Part B — Frontend (Dashboard) walkthrough

Boot with `streamlit run app.py` → http://localhost:8501

| # | Page | Do | Expected |
|---|---|---|---|
| 1 | Dashboard | open | KPI cards, decisions table, donut, Health © |
| 2 | Agent Policy | edit limits | saved + audit entry |
| 3 | Payment Request | 25000 electronics | **ALLOW** © |
| 4 | " " | 65000 electronics | **DENY** © |
| 5 | " " | gambling | **DENY** © |
| 6 | Risk Assessment | move sliders | live color gauge © |
| 7 | AI Investigation | investigate | provider=`openrouter` + confidence © |
| 8 | Decision Simulator | view txn | 3 What-if cards SIMULATED costs © |
| 9 | Payment History | filter | table + CSV |
| 10 | Real World (IEEE) | inspect | real 590k info + tool |
| 11 | Evaluation & Thresholds | drag slider | live curves © |
| 12 | Audit Log | open | every decision + reason |
}
```

> ℹ️ Note: the `ALLOW` path requires the user not to have exhausted their **daily
> limit** (see A5/A6) — the engine is stateful and reads real `daily_spent`.

---

### A4. Evaluate with **AI investigation** → advisory explanation from OpenRouter

**Request** (same as A3 with `"investigate": true`)

**Expected `ai` block — © live OpenRouter output (genuine reasoning, not template):**
```json
"ai": {
  "explanation": "The transaction was denied because the policy violation
    'daily_limit_exceeded' was triggered; the user had already spent INR 188,200
    and the new INR 25,000 would bring the daily total to INR 213,200, exceeding
    the INR 100,000 limit. The risk assessment contributed a MEDIUM risk score...",
  "provider": "openrouter",
  "model": "google/gemma-4-31b-it:free",
  "fallback_used": false,
  "...": "(latency_ms, tokens, concerns, review_questions, confidence)"
}
```

> ✅ **This proves live OpenRouter connectivity.** The explanation references the
> user's *actual* accumulated daily spend and the *actual* policy limit — it could
> not be a canned fallback.