"""
core/config.py — Centralized configuration for PayTrust AI local prototype.

Single source of truth for env vars. Never hard-code secrets.
Supports SQLite (default) and Postgres via DATABASE_URL override.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ──
    APP_NAME: str = "PayTrust AI"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-to-a-random-string-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Database ──
    DATABASE_URL: str = "sqlite:///./data/paytrust.db"

    # ── Razorpay (TEST MODE ONLY) ──
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None

    # ── LLM Providers (priority: OpenRouter → Groq → Gemini → deterministic) ──
    OPENROUTER_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # ── Circuit Breaker ──
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_TIMEOUT: int = 60
    CB_HALF_OPEN_MAX_CALLS: int = 3

    # ── Rate Limiting ──
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

    # ── Risk thresholds — documented, not magic numbers ──
    RISK_THRESHOLD_LOW: int = 30
    RISK_THRESHOLD_MEDIUM: int = 60
    RISK_THRESHOLD_HIGH: int = 80

    # ── Cost model (SIMULATED assumptions) ──
    FP_CUSTOMER_FRICTION_COST: float = 100.0
    FP_LOST_TRANSACTION_VALUE_MULTIPLIER: float = 1.0
    FP_SUPPORT_COST: float = 50.0
    FP_MERCHANT_IMPACT_COST: float = 200.0
    FN_FRAUD_EXPOSURE_MULTIPLIER: float = 1.0

    # ── Webhook ──
    WEBHOOK_MAX_RETRIES: int = 3
    WEBHOOK_RETRY_DELAY: int = 5
    WEBHOOK_DLQ_MAX_SIZE: int = 1000

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def sqlite_path(self) -> Optional[Path]:
        """Resolved filesystem path for sqlite file, if applicable."""
        if not self.is_sqlite:
            return None
        # Handle sqlite:///./data/paytrust.db and sqlite:///absolute
        url = self.DATABASE_URL
        path_str = url.split("sqlite:///")[-1]
        # Strip query params
        path_str = path_str.split("?")[0]
        p = Path(path_str)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parents[1] / p).resolve()
        return p

    def validate_for_production(self) -> list[str]:
        """Return list of warnings; empty means production-ready."""
        warnings: list[str] = []
        if self.SECRET_KEY.startswith("change-me"):
            warnings.append("SECRET_KEY is default — change in production")
        if self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET and not str(self.RAZORPAY_KEY_ID).startswith("rzp_test_"):
            warnings.append("RAZORPAY_KEY_ID does not look like TEST MODE (rzp_test_*)")
        return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
