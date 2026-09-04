"""
engines/ai_engine.py — Phase 9 AI Investigation (advisory only).

Provider priority: OpenRouter → Groq → Gemini → deterministic fallback.
Receives ONLY structured facts: transaction, policy_result, risk_result, decision.
Produces: explanation, summary, concerns, review_questions.
Never: executes payment, overrides policy, invents facts/scores.

Strict prompt + JSON output. Deterministic fallback ensures app works offline.
Circuit breaker (simple) tracks consecutive failures per provider.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("engines.ai")
settings = get_settings()

# ── Facts builder ──

def build_facts(payment: dict[str, Any] | None, policy_result: dict[str, Any] | None, risk_result: dict[str, Any] | None, decision: dict[str, Any] | None) -> dict[str, Any]:
    """
    Structured facts — the ONLY input to LLM. No raw PII, no free text invention.
    All args are optional-dict guarded so callers passing None never crash.
    """
    payment = payment or {}
    policy_result = policy_result or {}
    risk_result = risk_result or {}
    decision = decision or {}
    return {
        "transaction": {
            "request_id": payment.get("request_id"),
            "amount": payment.get("amount"),
            "currency": payment.get("currency"),
            "category": payment.get("category"),
            "merchant": payment.get("merchant_name"),
            "merchant_id": payment.get("merchant_id"),
            "user_id": payment.get("user_id"),
            "agent_id": payment.get("agent_id"),
            "timestamp": payment.get("timestamp") or payment.get("created_at"),
            "description": payment.get("description"),
            "agent_reason": payment.get("agent_reason"),
        },
        "policy_result": {
            "authorized": policy_result.get("authorized"),
            "requires_approval": policy_result.get("requires_approval"),
            "violations": policy_result.get("violations", []),
            "reasons": policy_result.get("reasons", [])[:4],
        },
        "risk_result": {
            "risk_score": risk_result.get("risk_score"),
            "risk_level": risk_result.get("risk_level"),
            "factors": risk_result.get("factors", [])[:5],
        },
        "decision": {
            "decision": decision.get("decision"),
            "risk_score": decision.get("risk_score"),
            "risk_level": decision.get("risk_level"),
            "reasons": decision.get("reasons", [])[:3],
        },
        "policy_thresholds": {
            "daily_limit": (policy_result.get("policy") or {}).get("daily_limit"),
            "max_transaction": (policy_result.get("policy") or {}).get("max_transaction"),
            "approval_threshold": (policy_result.get("policy") or {}).get("approval_threshold"),
        },
    }

STRICT_PROMPT_TEMPLATE = """You are PayTrust AI investigation assistant. You are ADVISORY ONLY.
You must NOT execute payments, override policy, or invent facts.

You receive STRUCTURED FACTS (JSON) from deterministic engines:
{facts_json}

RULES:
- Only use provided facts. Do not invent amounts, merchants, scores, or violations.
- Do not create new risk scores — use the provided risk_score.
- Explain in 2-4 sentences why the deterministic decision was made, citing violations/factors.
- List 1-3 concerns (if any) based on factors/violations.
- Propose 2-3 review questions for a human analyst.
- State confidence 0.0-1.0 based on evidence clarity.
- Output JSON ONLY with keys: explanation, summary, concerns, review_questions, confidence

Example JSON:
{{"explanation": "...", "summary": "...", "concerns": ["..."], "review_questions": ["..."], "confidence": 0.82}}

Now analyze the provided facts and output JSON.
"""

# ── Provider abstraction (sync) ──

@dataclass
class ProviderState:
    failures: int = 0
    last_failure: float = 0.0
    open_until: float = 0.0
    successes: int = 0

class LLMProvider:
    name: str
    model: str
    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model
        self.state = ProviderState()
        self.timeout = 12.0

    def is_circuit_open(self) -> bool:
        return time.time() < self.state.open_until

    def record_success(self):
        self.state.failures = 0
        self.state.successes += 1

    def record_failure(self):
        self.state.failures += 1
        self.state.last_failure = time.time()
        if self.state.failures >= settings.CB_FAILURE_THRESHOLD:
            self.state.open_until = time.time() + settings.CB_RECOVERY_TIMEOUT
            logger.warning(f"AI provider {self.name} circuit OPEN for {settings.CB_RECOVERY_TIMEOUT}s")

    def call(self, prompt: str) -> tuple[str, int, float, Optional[str]]:
        """
        Returns (content, tokens, latency_ms, error)
        """
        raise NotImplementedError

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "openai/gpt-4o-mini", fallbacks: Optional[list[str]] = None):
        super().__init__("openrouter", model)
        self.api_key = api_key
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        # Free-tier pools get congested — OpenRouter auto-routes down this chain on 429.
        self.fallbacks = [m.strip() for m in (fallbacks or []) if m.strip()]

    def call(self, prompt: str):
        if self.is_circuit_open():
            return "", 0, 0, "circuit_open"
        start = time.time()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://paytrust.ai", "X-Title": "PayTrust AI"}
        payload: dict[str, Any] = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 800}
        if self.fallbacks:
            payload["models"] = [self.model, *self.fallbacks]
        # One polite client-side retry on 429 (upstream pools recover in seconds).
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(self.url, headers=headers, json=payload)
                    if resp.status_code == 429 and attempt == 0:
                        # Respect Retry-After when provided, else short backoff (SIM: bounded wait).
                        wait = float(resp.headers.get("retry-after", "3") or 3)
                        time.sleep(min(wait, 8.0))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {}).get("total_tokens", 0)
                    latency = (time.time() - start) * 1000
                    self.record_success()
                    return content, tokens, latency, None
            except Exception as exc:
                if attempt == 1:
                    self.record_failure()
                    latency = (time.time() - start) * 1000
                    return "", 0, latency, str(exc)[:300]
                # Non-429 errors: no point retrying immediately — surface on 2nd pass.
                if not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429):
                    self.record_failure()
                    latency = (time.time() - start) * 1000
                    return "", 0, latency, str(exc)[:300]
        return "", 0, (time.time() - start) * 1000, "unreachable"

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "llama-3.1-70b-versatile"):
        super().__init__("groq", model)
        self.api_key = api_key
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def call(self, prompt: str):
        if self.is_circuit_open():
            return "", 0, 0, "circuit_open"
        start = time.time()
        try:
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 800}
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                latency = (time.time() - start) * 1000
                self.record_success()
                return content, tokens, latency, None
        except Exception as exc:
            self.record_failure()
            latency = (time.time() - start) * 1000
            return "", 0, latency, str(exc)[:300]

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        super().__init__("gemini", model)
        self.api_key = api_key
        self.model = model

    def call(self, prompt: str):
        if self.is_circuit_open():
            return "", 0, 0, "circuit_open"
        start = time.time()
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}}
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
                latency = (time.time() - start) * 1000
                self.record_success()
                return content, tokens, latency, None
        except Exception as exc:
            self.record_failure()
            latency = (time.time() - start) * 1000
            return "", 0, latency, str(exc)[:300]

# Deterministic fallback — no network
class DeterministicProvider(LLMProvider):
    def __init__(self):
        super().__init__("deterministic", "rule-based-v1")

    def call(self, prompt: str):
        # Not used directly — AIEngine calls _deterministic_explanation
        return json.dumps({"explanation": "Deterministic fallback", "summary": "Rule-based", "concerns": [], "review_questions": [], "confidence": 0.5}), 0, 0, None

def _deterministic_explanation(facts: dict[str, Any]) -> dict[str, Any]:
    pol = facts.get("policy_result", {})
    risk = facts.get("risk_result", {})
    dec = facts.get("decision", {})
    txn = facts.get("transaction", {})
    violations = pol.get("violations", [])
    factors = risk.get("factors", [])
    decision = dec.get("decision", "UNKNOWN")
    risk_score = risk.get("risk_score", 0)
    risk_level = risk.get("risk_level", "LOW")

    # Build explanation from facts only
    parts = []
    if violations:
        parts.append(f"Policy violations: {', '.join(violations)}.")
    else:
        parts.append("No policy violations.")
    if factors:
        top = factors[0]
        parts.append(f"Top risk factor: {top.get('name')} ({top.get('severity')}, +{top.get('score')}).")
    parts.append(f"Deterministic decision is {decision} at risk {risk_level} ({risk_score}).")
    explanation = " ".join(parts)

    concerns = []
    for f in factors[:2]:
        if f.get("severity") in ("high","critical"):
            concerns.append(f"{f.get('name')}: {f.get('details')}")
    if "category_blocked" in violations:
        concerns.append("Blocked category — should remain denied even if amount is low")
    if not concerns:
        concerns.append("No strong concerns beyond deterministic factors")

    review_qs = []
    if dec.get("decision") == "ASK_USER":
        review_qs.append("Does the user confirm this agent should spend this amount?")
        review_qs.append("Is the merchant and category expected for this user?")
    elif dec.get("decision") == "DENY":
        review_qs.append("Should this policy threshold be adjusted for this user/agent?")
        review_qs.append("Is there a legitimate reason for this high-risk pattern?")
    else:
        review_qs.append("Confirm agent is authorized for this category?")
        review_qs.append("Check recent transaction history for anomalies?")

    # Confidence based on evidence clarity
    if risk_level in ("HIGH","CRITICAL") and violations:
        conf = 0.88
    elif risk_level == "MEDIUM":
        conf = 0.72
    else:
        conf = 0.65
    # Lower if no violations but high risk (contradictory)
    if not violations and risk_level in ("HIGH","CRITICAL"):
        conf = 0.55

    return {
        "explanation": explanation,
        "summary": f"{decision} at {risk_level} ({risk_score}) — {'violations: '+', '.join(violations) if violations else 'policy pass'}",
        "concerns": concerns[:3],
        "review_questions": review_qs[:3],
        "confidence": conf,
    }

class AIEngine:
    def __init__(self):
        self.providers: list[LLMProvider] = []
        self._init_providers()

    def _init_providers(self):
        if settings.OPENROUTER_API_KEY:
            model = getattr(settings, "OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
            fallbacks = [
                m.strip() for m in getattr(settings, "OPENROUTER_FALLBACK_MODELS", "").split(",") if m.strip()
            ]
            self.providers.append(OpenRouterProvider(settings.OPENROUTER_API_KEY, model=model, fallbacks=fallbacks))
        if settings.GROQ_API_KEY:
            self.providers.append(GroqProvider(settings.GROQ_API_KEY))
        if settings.GEMINI_API_KEY:
            self.providers.append(GeminiProvider(settings.GEMINI_API_KEY))
        # Deterministic always last
        self.providers.append(DeterministicProvider())

    def investigate(self, facts: dict[str, Any]) -> dict[str, Any]:
        """
        Run investigation. Returns dict with keys:
          explanation, summary, concerns, review_questions, confidence,
          model, provider, latency_ms, fallback_used, error, raw_content
        """
        facts_json = json.dumps(facts, indent=2, default=str)
        prompt = STRICT_PROMPT_TEMPLATE.format(facts_json=facts_json)

        last_error = None
        for idx, prov in enumerate(self.providers):
            if isinstance(prov, DeterministicProvider):
                # Deterministic
                det = _deterministic_explanation(facts)
                return {
                    "explanation": det["explanation"],
                    "summary": det["summary"],
                    "concerns": det["concerns"],
                    "review_questions": det["review_questions"],
                    "confidence": det["confidence"],
                    "model": prov.model,
                    "provider": prov.name,
                    "latency_ms": 0,
                    "fallback_used": idx > 0,
                    "error": last_error,
                    "raw_content": json.dumps(det),
                }

            content, tokens, latency, err = prov.call(prompt)
            if err:
                last_error = f"{prov.name}: {err}"
                logger.warning(f"AI provider {prov.name} failed: {err} — trying next")
                continue
            # Try parse JSON
            try:
                # Extract JSON block if wrapped in markdown
                text = content.strip()
                if text.startswith("```"):
                    # strip code fence
                    text = text.split("```")[1]
                    if text.lstrip().startswith("json"):
                        text = text.lstrip()[4:]
                    text = text.strip()
                parsed = json.loads(text)
                # Validate keys
                explanation = str(parsed.get("explanation", "")).strip()
                if not explanation:
                    raise ValueError("Missing explanation")
                return {
                    "explanation": explanation,
                    "summary": str(parsed.get("summary", explanation[:120])),
                    "concerns": list(parsed.get("concerns", []))[:3],
                    "review_questions": list(parsed.get("review_questions", []))[:3],
                    "confidence": float(parsed.get("confidence", 0.7)),
                    "model": prov.model,
                    "provider": prov.name,
                    "latency_ms": latency,
                    "fallback_used": idx > 0,
                    "error": None,
                    "raw_content": content,
                }
            except Exception as parse_err:
                last_error = f"{prov.name} parse: {parse_err} — raw: {content[:200]}"
                logger.warning(last_error)
                continue

        # All providers failed → deterministic
        det = _deterministic_explanation(facts)
        return {
            "explanation": det["explanation"],
            "summary": det["summary"],
            "concerns": det["concerns"],
            "review_questions": det["review_questions"],
            "confidence": det["confidence"],
            "model": "rule-based-v1",
            "provider": "deterministic",
            "latency_ms": 0,
            "fallback_used": True,
            "error": last_error,
            "raw_content": json.dumps(det),
        }
