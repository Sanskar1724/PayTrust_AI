# DEMO.md — 2-Minute Judge Demo Script (Razorpay Buildathon, Track 02)

> Purpose: a crisp, honest, evidence-driven walkthrough. Everything shown is verifiable
> in this repo — no fake numbers, no fake AI.

## 0. Prepare beforehand (external artifacts)

- **Deploy** (optional but strongest): follow `docs/DEPLOYMENT.md:1` → public HF Space URL.
- **Screen-record** this script exactly (Loom / OBS / StreamYard) — 5–8 min version is fine too.

- **GitHub repo**: [`github.com/Sanskar1724/PayTrust_AI`](https://github.com/Sanskar1724/PayTrust_AI)
- **Screenshots** ready: dashboard, Payment `ALLOW → DENY`, threshold tool, audit log,
  OpenAPI `/docs`, webhook dupe.
Submission csv first rows.

- **Add a live LLM key** (`OPENROUTER_API_KEY` free / `GROQ_API_KEY` / `GEMINI_API_KEY`) if you want the live
  provider call; offline it degrades to deterministic fallback (still honest(.

## 1. Script (timed(

**[0:00–0:15] Hook — problem & one loss class**
> "AI agents are about to spend money on your behalf. How do we know a payment is safe,
> *why* it’s suspicious, and what the most economically-justified defensive action is?"
> One loss class: **payment abuse / fraud-spike detection** — defense-only.



**[0:15–0:40] End-to-end decision — Payment Request**
App → Payment Request: `TechMart Electronics` 25k `electronics` → **ALLOW** (green, ~11 risk(
Then: amount 65k → **DENY** (`max_transaction_exceeded`); category `gambling` → **DENY**;
amount 35k → **ASK_USER**. Deterministic engines are final & instant.
Show the decision pills (ALLOW green / ASK yellow / DENY red(.



**[0:40–1:05] Why? — Risk factors + AI investigation + simulator**
Risk Assessment: 7 transparent dimensions → score + factors (name/severity/details(.
AI Investigation: structured facts only (**no invented evidence**#, provider chain (OpenRouter→Groq→Gemini→deterministic(.
Decision Simulator: "What if ALLOW / ASK_USER / DENY?" → SIMULATED costs, all labeled.



**[1:05–1:30] Real ML, honest — Threshold Decision Tool**
Real World (IEEE): trained chunked on **590k real transactions** (no leak,: temporal held-out 3,000-row test(. Threshold tool: move the slider → live precision/recall/FPR/confusion + SIMULATED
fraud-exposure vs false-positive-cost trade-off. Show the honest numbers (PR-AUC 0.31,
F1 0.29 @ p≈0.96( — *not tuned for marketing*; that’s requirement #14(.



**[1:30–1:50] API + webhook (buildability(**
FastAPI `/docs`: `POST /v1/evaluate` idempotent (`duplicate: true`(, `GET /v1/threshold/recommend`وه.
Razorpay webhook: raw-body HMAC verified, duplicate idempotent; audit trail everywhere.



**[1:50–2:00] Reliability + wrap**
> "Failure recovery: LLM outage → deterministic fallback; webhook dupes → idempotent ignore;
> outlier cost estimates → SIMULATED labels. 128 tests pass on `main` (GitHub Actions CI(.
> Deterministic is final; AI is advisory; Razorpay TEST MODE; no live money — defense-only."

## 2. Submission text / slide bullets

- Real problem, one loss class, working UI + REST (15/15 brief requirements — see `docs/ROADMAP.md:1`(
- Evidence-driven: factors, audit trial, counterfactual costs, honest IEEE held-out metrics.

- Engineering: 128 tests, CI, HMAC webhooks, idempotency, redacted logs, API-key auth + rate limit(
- Failure recovery: provider fallback, webhook DLQ/idempotency, graceful degradation(
- Artifacts to link: repo, deployed Space URL, video, `evaluation/submission.csv` (506,691 predictions(,
  `evaluation/ieee_report.json`, `docs/API.md`, `docs/ROADMAP.md`