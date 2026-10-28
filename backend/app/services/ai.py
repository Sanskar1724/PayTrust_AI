"""Advisory AI investigation. Providers are tried in order (OpenRouter → Groq → Gemini),
each behind a circuit breaker; the deterministic explanation is the final fallback, so this
never fails. The model only sees structured facts and can never change a decision."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings
from app.domain.explain import deterministic_explanation
from app.log import get_logger

logger = get_logger("ai")

PROMPT = """You are the PayTrust investigation assistant. You are ADVISORY ONLY: you cannot
approve, deny or execute payments and you must not invent facts, amounts or scores.

Structured facts from the deterministic engines:
{facts}

Write JSON only, with exactly these keys:
  "explanation": 2-4 plain sentences on why the engines decided what they did, citing the facts
  "summary": one short line
  "concerns": 1-3 short strings
  "review_questions": 2-3 questions a human reviewer should ask
  "confidence": number 0.0-1.0 reflecting how clear the evidence is
"""


@dataclass
class Breaker:
    threshold: int
    recovery_seconds: int
    failures: int = 0
    open_until: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def available(self) -> bool:
        return time.monotonic() >= self.open_until

    def success(self) -> None:
        with self.lock:
            self.failures = 0

    def failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.recovery_seconds
                self.failures = 0


class Provider:
    name = "base"

    def __init__(self, model: str):
        s = get_settings()
        self.model = model
        self.breaker = Breaker(s.CB_FAILURE_THRESHOLD, s.CB_RECOVERY_SECONDS)

    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class _OpenAICompatible(Provider):
    url = ""

    def __init__(self, api_key: str, model: str, extra: dict[str, Any] | None = None):
        super().__init__(model)
        self.api_key = api_key
        self.extra = extra or {}

    def complete(self, prompt: str) -> str:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1, "max_tokens": 700, **self.extra}
        with httpx.Client(timeout=get_settings().AI_TIMEOUT_SECONDS) as client:
            resp = client.post(self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class OpenRouter(_OpenAICompatible):
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/chat/completions"


class Groq(_OpenAICompatible):
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"


class Gemini(Provider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        super().__init__(model)
        self.api_key = api_key

    def complete(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 700}}
        with httpx.Client(timeout=get_settings().AI_TIMEOUT_SECONDS) as client:
            resp = client.post(url, headers={"x-goog-api-key": self.api_key}, json=body)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def parse_response(text: str) -> dict[str, Any]:
    """Extract and validate the JSON object from a model reply."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start:end + 1])
    explanation = str(data.get("explanation") or "").strip()
    if not explanation:
        raise ValueError("missing explanation")
    confidence = float(data.get("confidence", 0.7))
    return {
        "explanation": explanation,
        "summary": str(data.get("summary") or explanation[:140]),
        "concerns": [str(c) for c in (data.get("concerns") or [])][:3],
        "review_questions": [str(q) for q in (data.get("review_questions") or [])][:3],
        "confidence": max(0.0, min(1.0, confidence)),
    }


class Investigator:
    def __init__(self, providers: list[Provider] | None = None):
        self.providers = providers if providers is not None else self._configured()

    @staticmethod
    def _configured() -> list[Provider]:
        s = get_settings()
        out: list[Provider] = []
        if s.OPENROUTER_API_KEY:
            fallbacks = [m.strip() for m in s.OPENROUTER_FALLBACK_MODELS.split(",") if m.strip()]
            extra = {"models": [s.OPENROUTER_MODEL, *fallbacks]} if fallbacks else {}
            out.append(OpenRouter(s.OPENROUTER_API_KEY, s.OPENROUTER_MODEL, extra))
        if s.GROQ_API_KEY:
            out.append(Groq(s.GROQ_API_KEY, s.GROQ_MODEL))
        if s.GEMINI_API_KEY:
            out.append(Gemini(s.GEMINI_API_KEY, s.GEMINI_MODEL))
        return out

    def investigate(self, facts: dict[str, Any]) -> dict[str, Any]:
        prompt = PROMPT.format(facts=json.dumps(facts, indent=2, default=str))
        errors: list[str] = []
        for provider in self.providers:
            if not provider.breaker.available():
                errors.append(f"{provider.name}: circuit open")
                continue
            started = time.perf_counter()
            try:
                result = parse_response(provider.complete(prompt))
            except Exception as exc:
                provider.breaker.failure()
                errors.append(f"{provider.name}: {str(exc)[:160]}")
                logger.warning(f"AI provider {provider.name} failed: {exc}")
                continue
            provider.breaker.success()
            return result | {
                "provider": provider.name,
                "model": provider.model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "fallback_used": bool(errors),
                "errors": errors,
                "advisory_only": True,
            }
        return deterministic_explanation(facts) | {
            "provider": "deterministic",
            "model": "rules-v2",
            "latency_ms": 0.0,
            "fallback_used": bool(self.providers),
            "errors": errors,
            "advisory_only": True,
        }


_investigator: Investigator | None = None


def get_investigator() -> Investigator:
    global _investigator
    if _investigator is None:
        _investigator = Investigator()
    return _investigator
