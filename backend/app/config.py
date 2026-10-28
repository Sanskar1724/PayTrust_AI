"""Application settings — the single source of truth for environment configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──
    APP_NAME: str = "PayTrust AI"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    SECRET_KEY: str = "dev-insecure-secret-change-me-0123456789abcdef"
    JWT_EXPIRE_MINUTES: int = 12 * 60
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ── Bootstrap admin (created on startup only when no operator exists) ──
    ADMIN_EMAIL: str = "admin@paytrust.local"
    ADMIN_PASSWORD: str = "admin12345"
    SEED_DEMO_DATA: bool = True
    # Migrate + bootstrap inside the app on startup. Containers set this to false and run
    # `python -m app.cli init` once before starting workers, so workers never race on it.
    AUTO_MIGRATE: bool = True

    # ── Infrastructure ──
    DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'paytrust.db').as_posix()}"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    REDIS_URL: str | None = None  # optional — enables shared rate limits + multi-instance live feed

    # ── Rate limiting (per API key / per operator) ──
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ── Payment rules ──
    SPEND_TIMEZONE: str = "Asia/Kolkata"  # "today" for daily limits is computed in this zone
    APPROVAL_TTL_MINUTES: int = 30
    RISK_THRESHOLD_LOW: int = 30
    RISK_THRESHOLD_MEDIUM: int = 60
    RISK_THRESHOLD_HIGH: int = 80

    # ── Counterfactual cost model (SIMULATED assumptions) ──
    FP_CUSTOMER_FRICTION_COST: float = 100.0
    FP_LOST_TRANSACTION_VALUE_MULTIPLIER: float = 1.0
    FP_SUPPORT_COST: float = 50.0
    FP_MERCHANT_IMPACT_COST: float = 200.0
    FN_FRAUD_EXPOSURE_MULTIPLIER: float = 1.0

    # ── AI investigation (advisory only) ──
    AI_AUTO_INVESTIGATE: bool = True  # run in background for ASK_USER / DENY decisions
    AI_TIMEOUT_SECONDS: float = 12.0
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"
    OPENROUTER_FALLBACK_MODELS: str = "google/gemma-4-26b-a4b-it:free,openrouter/free"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    CB_FAILURE_THRESHOLD: int = 3
    CB_RECOVERY_SECONDS: int = 60

    # ── Razorpay ──
    # simulated: no network, fake order ids · test: rzp_test_* keys · live: rzp_live_* keys
    RAZORPAY_MODE: Literal["simulated", "test", "live"] = "simulated"
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None

    # ── Outbound callbacks to agents ──
    CALLBACK_TIMEOUT_SECONDS: float = 5.0
    CALLBACK_MAX_ATTEMPTS: int = 3

    # ── Agent Arena ──
    ARENA_BASE_URL: str = "http://127.0.0.1:8000"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    def production_problems(self) -> list[str]:
        """Config that is acceptable in development but unsafe in production."""
        problems: list[str] = []
        if self.SECRET_KEY.startswith("dev-insecure") or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY must be a random string of at least 32 characters")
        if self.ADMIN_PASSWORD == "admin12345":
            problems.append("ADMIN_PASSWORD is the development default")
        if "*" in self.cors_origins:
            problems.append("CORS_ALLOW_ORIGINS must be an explicit allowlist")
        if self.is_sqlite:
            problems.append("DATABASE_URL must point to PostgreSQL")
        if self.RAZORPAY_MODE != "simulated" and not (self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET):
            problems.append("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET required for RAZORPAY_MODE test/live")
        if self.RAZORPAY_MODE != "simulated" and not self.RAZORPAY_WEBHOOK_SECRET:
            problems.append("RAZORPAY_WEBHOOK_SECRET required when Razorpay is enabled")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
