"""api/routers/health.py — Liveness & readiness probes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from api.schemas import HealthResponse, ReadyResponse
from core.config import get_settings
from database.database import get_connection, get_db_path

router = APIRouter(tags=["health"])
settings = get_settings()


def _db_path(request: Request) -> Path:
    return getattr(request.app.state, "db_path", None) or get_db_path()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health(request: Request):
    db_path = _db_path(request)
    db_ok = False
    try:
        conn = get_connection(db_path)
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        database={"path": str(db_path), "ok": db_ok},
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
def ready(request: Request):
    checks: list[str] = []
    db_ok = False
    try:
        conn = get_connection(_db_path(request))
        conn.execute("SELECT COUNT(*) FROM payment_requests")
        conn.close()
        db_ok = True
        checks.append("database:ok")
    except Exception as exc:
        checks.append(f"database:error:{str(exc)[:80]}")

    root = Path(__file__).resolve().parents[2]  # paytrust-ai/
    models = {
        "ieee_model.pkl": (root / "models" / "ieee_model.pkl").exists(),
        "risk_model.pkl": (root / "models" / "risk_model.pkl").exists(),
    }
    checks.append(f"models:ieee={models['ieee_model.pkl']},risk={models['risk_model.pkl']}")
    ready_val = db_ok
    return ReadyResponse(ready=ready_val, database=db_ok, models=models, checks=checks)