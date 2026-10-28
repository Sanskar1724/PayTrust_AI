"""Liveness, readiness and Prometheus metrics."""
from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness — the process is up")
def health():
    s = get_settings()
    return {"status": "ok", "version": s.APP_VERSION, "environment": s.ENVIRONMENT}


@router.get("/ready", summary="Readiness — dependencies are reachable")
def ready():
    s = get_settings()
    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    if s.REDIS_URL:
        try:
            import redis

            redis.Redis.from_url(s.REDIS_URL, socket_timeout=2).ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks},
                        status_code=200 if healthy else 503)


@router.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
