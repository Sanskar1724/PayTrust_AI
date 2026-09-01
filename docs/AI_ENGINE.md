# AI_ENGINE.md — Phase 9

## Role
**Advisory only.** The LLM explains and investigates; it never executes payments, never overrides `PolicyEngine`/`RiskEngine`/`DecisionEngine`, and never invents facts.

## Facts In, Not Raw Data

`engines/ai_engine.py:build_facts` builds the **only** input to the LLM:

```json
{
  "transaction": {"request_id","amount","currency","category","merchant","user_id","agent_id","timestamp",...},
  "policy_result": {"authorized","requires_approval","violations","reasons"},
  "risk_result": {"risk_score","risk_level","factors"},
  "decision": {"decision","risk_score","risk_level","reasons"}
}
```

No raw PII beyond IDs, no card numbers, no secrets.

## Provider Priority & Fallback

`engines/ai_engine.py:AIEngine._init_providers`:

1. `OpenRouterProvider` (`openai/gpt-4o-mini`) — if `OPENROUTER_API_KEY` set
2. `GroqProvider` (`llama-3.1-70b-versatile`) — if `GROQ_API_KEY` set
3. `GeminiProvider` (`gemini-1.5-flash`) — if `GEMINI_API_KEY` set
4. `DeterministicProvider` — always, rule-based `_deterministic_explanation`

Each provider has a simple circuit: `failures >= CB_FAILURE_THRESHOLD (5)` → `OPEN` for `CB_RECOVERY_TIMEOUT` (60s). Failures are counted per-provider (`engines/ai_engine.py:ProviderState`).

If a provider returns non-JSON, timeouts, or `invalid_api_key`, the engine tries the next. If all fail, it returns `_deterministic_explanation`.

## Strict Prompt

`engines/ai_engine.py:STRICT_PROMPT_TEMPLATE`:

- “You are ADVISORY ONLY. Do not execute payments, override policy, or invent facts.”
- “Only use provided facts. Do not invent amounts, merchants, scores, or violations.”
- “Output JSON ONLY with keys: explanation, summary, concerns, review_questions, confidence.”

Output example:
```json
{"explanation":"Policy violations: max_transaction_exceeded. Top risk factor amount_risk (high). Deterministic decision is DENY at HIGH (78).","summary":"DENY at HIGH (78) — violations: max_transaction_exceeded","concerns":["amount_risk: Amount INR 65,000 >= 50000"],"review_questions":["Should this threshold be adjusted?"],"confidence":0.88}
```

The engine extracts JSON, even if wrapped in ```json fences.

## Deterministic Fallback

`engines/ai_engine.py:_deterministic_explanation` builds explanation purely from violations/factors without network:

- `explanation` = `Policy violations: ...` + `Top risk factor: ...` + `Deterministic decision is ...`
- `concerns` = top 2 high/critical factors or blocked-category note
- `review_questions` = tailored to `ALLOW`/`ASK`/`DENY`
- `confidence` = 0.88 if HIGH+violations, 0.72 if MEDIUM, 0.65 otherwise (0.55 if contradictory high risk without violations)

App remains usable offline.

## Testing

`tests/test_ai_engine.py:1` mocks providers:

- `test_ai_engine_offline_uses_deterministic` — no keys → deterministic
- `test_ai_engine_openrouter_success_mocked` — mocked JSON success
- `test_ai_engine_openrouter_failure_fallback_to_groq` — first fails, second succeeds, `fallback_used=True`
- `test_ai_engine_all_providers_fail_uses_deterministic` — all fail → deterministic
- `test_ai_engine_malformed_response_fallback` — non-JSON → fallback
- `test_ai_engine_invalid_api_key_handled` — 401 → fallback
- `test_app_remains_usable_without_ai` — decision unchanged

## Logging & Safety

- Never logs `raw_body` secrets; `core/logger.py:18` redacts `sk-or-v1`, `rzp_test`, `gsk_`.
- `core/security.py:audit_log` redacts `api_key`/`secret`.
- UI (`app.py:AI Investigation`) shows `Model: ... Provider: ... Fallback: ... Latency: ...ms` and warns “LLM is advisory”.

## Failure Cases Documented

- Timeout → next provider
- Malformed JSON → next provider
- All providers timeout → deterministic fallback
- Contradictory evidence (high risk without violations) → confidence 0.55
- Insufficient evidence → deterministic still returns explanation, confidence 0.65
