"""api/main.py — PayTrust AI HTTP service (FastAPI) over the tested engines.

Run locally (from paytrust-ai/):
    python -m api.main                 # → http://localhost:8000  | Swagger /docs
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Deployment: build with the provided Dockerfile, run behind Caddy/nginx for TLS.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import evaluate, evaluation, health, payments, threshold, webhooks
from api.security import RequestIdMiddleware
from core.config import Settings, get_settings
from core.logger import configure_root_logging, get_logger
from database.database import get_db_path, init_db

logger = get_logger("api")
settings = get_settings()


def _json_safe_errors(errors: list) -> list:
    """Pydantic v2 error entries may embed exception objects in `ctx` — make JSON-safe."""
    out = []
    for e in errors:
        d = dict(e)
        ctx = d.get("ctx")
        if isinstance(ctx, dict) and isinstance(ctx.get("error"), BaseException):
            d["ctx"] = {**ctx, "error": str(ctx["error"])}
        out.append(d)
    return out


def create_app(settings_obj: Settings | None = None, db_path: Path | None = None) -> FastAPI:
    """Build the FastAPI app. `db_path` is used by tests to isolate a tmp DB."""
    s = settings_obj or settings
    configure_root_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        path = db_path or get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(seed=True, db_path=path)
        app.state.db_path = path
        # Production boot guard — refuse unsafe config loudly.
        if s.ENVIRONMENT.lower() == "production":
            warns = s.validate_for_production()
            if warns:
                raise RuntimeError(
                    f"Refusing to boot in PRODUCTION with unsafe config: {warns}"
                )
        logger.info(f"API started env={s.ENVIRONMENT} db={path}")
        yield

    app = FastAPI(
        title=f"{s.APP_NAME} API",
        version=s.APP_VERSION,
        description=(
            "Evidence-driven payment risk & loss-prevention API. "
            "Deterministic Policy → Risk → Decision engines (LLM advisory only). "
            "Razorpay TEST MODE only. All costs in the simulator are SIMULATED/ESTIMATED."
        ),
        lifespan=lifespan,
    )

    # Eagerly set so TestClient calls work even without lifespan.
    app.state.db_path = db_path
    app.state.settings = s

    origins = [o.strip() for o in s.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
    allow_credentials = "*" not in origins
    app.add_middleware(CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request, exc: RequestValidationError):
        # Consistent error contract: {"detail": {"code": "VALIDATION_ERROR", "errors": [...]}}
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "VALIDATION_ERROR", "errors": _json_safe_errors(exc.errors())}},
        )

    app.include_router(health.router)
    app.include_router(evaluate.router)
    app.include_router(payments.router)
    app.include_router(webhooks.router)
    app.include_router(evaluation.router)
    app.include_router(threshold.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)