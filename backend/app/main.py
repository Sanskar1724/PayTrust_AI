"""PayTrust AI — FastAPI application.

    uvicorn app.main:app --reload            # from backend/
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import db
from app.api.routes import arena, auth, directory, health, insights, payments
from app.arena.runner import fail_interrupted_runs
from app.config import REPO_DIR, get_settings
from app.errors import AppError
from app.log import configure_logging, get_logger, get_request_id, set_request_id
from app.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.services import approvals, seed, tasks
from app.services.events import bus

logger = get_logger("app")
EXPIRY_SWEEP_SECONDS = 30
FRONTEND_DIST = REPO_DIR / "frontend" / "dist"


def run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")


async def _expiry_sweeper() -> None:
    while True:
        await asyncio.sleep(EXPIRY_SWEEP_SECONDS)
        try:
            await run_in_threadpool(approvals.expire_due)
        except Exception:
            logger.exception("Approval expiry sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.LOG_JSON)
    if s.ENVIRONMENT == "production":
        problems = s.production_problems()
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    db.init_engine()
    if app.state.manage_schema and s.AUTO_MIGRATE:
        await run_in_threadpool(run_migrations)
        with db.session_scope() as session:
            seed.bootstrap(session)
    fail_interrupted_runs()
    bus.start(s.REDIS_URL)
    sweeper = asyncio.create_task(_expiry_sweeper())
    logger.info(f"{s.APP_NAME} {s.APP_VERSION} started ({s.ENVIRONMENT}, {'sqlite' if s.is_sqlite else 'postgres'})")
    try:
        yield
    finally:
        sweeper.cancel()
        bus.stop()
        tasks.shutdown()


class RequestContextMiddleware:
    """Request id, access metrics and security headers. Pure ASGI so streaming responses pass through."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        rid = set_request_id((headers.get(b"x-request-id") or b"").decode("latin-1") or None)
        started = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                extra = [
                    (b"x-request-id", rid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            HTTP_REQUESTS.labels(scope["method"], path, str(status_holder["code"])).inc()
            HTTP_LATENCY.labels(scope["method"], path).observe(time.perf_counter() - started)


def _error(status: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": get_request_id()}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


def create_app(manage_schema: bool = True) -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f"{s.APP_NAME} API",
        version=s.APP_VERSION,
        description=(
            "Payment authorization for AI agents. Every payment an agent wants to make goes through "
            "deterministic Policy → Risk → Decision engines and comes back ALLOW, ASK_USER or DENY "
            "with its evidence. AI explanations are advisory and never change a decision.\n\n"
            "**Agents** authenticate with `X-API-Key`. **Operators** sign in at `/v1/auth/login` and "
            "send `Authorization: Bearer <token>`."
        ),
        lifespan=lifespan,
    )
    app.state.manage_schema = manage_schema

    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "Retry-After"])
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"Retry-After": str(exc.retry_after)} if hasattr(exc, "retry_after") else None
        return _error(exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
                   for e in exc.errors()]
        return _error(422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return _error(500, "INTERNAL_ERROR", "Something went wrong. Quote the request id when reporting it.")

    for module in (health, auth, payments, directory, insights, arena):
        app.include_router(module.router)

    if FRONTEND_DIST.is_dir():  # single-service deploys: the API also serves the built UI
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("v1/"):
                return _error(404, "NOT_FOUND", "Not found")
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
