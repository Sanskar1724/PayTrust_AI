"""Durable background jobs: a transactional outbox with retries and a dead-letter queue.

Work that must happen after a decision but must not block it (create the payment order,
write the AI explanation, call the agent back) is written as a `jobs` row IN THE SAME
TRANSACTION as the change that needs it. If that transaction commits, the job exists;
if the process dies a millisecond later, the job is still there and runs after restart.

Execution
  * A worker claims due jobs with a compare-and-set UPDATE (safe across processes, on
    SQLite and PostgreSQL alike) and holds a lease (`locked_until`). A job whose worker
    died is reclaimed by any worker once the lease runs out.
  * `attempts` is the fencing token: a worker only records the outcome if the job still
    has the attempt number it claimed, so a slow, superseded run cannot overwrite a newer one.
  * Failures retry with exponential backoff + jitter. After `max_attempts`, or on a
    PermanentFailure, the job becomes DEAD and its kind's `on_dead` hook records the final
    outcome (e.g. ORDER_FAILED). Operators can retry dead jobs from the console.

Handlers must be idempotent: delivery is at-least-once.

Tests (and `tasks.run_inline(True)`) execute due jobs synchronously on `kick()`.
"""
from __future__ import annotations

import random
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.log import get_logger
from app.metrics import JOBS
from app.models import Job, JobStatus
from app.services import audit, tasks

logger = get_logger("jobs")


class PermanentFailure(Exception):
    """Retrying cannot help (e.g. an unsafe callback URL): dead-letter immediately."""


@dataclass(frozen=True)
class JobContext:
    id: int
    kind: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    request_id: str | None

    @property
    def is_last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


@dataclass(frozen=True)
class Handler:
    run: Callable[[JobContext], None]
    on_dead: Callable[[JobContext, str, bool], None] | None  # (job, error, permanent)
    max_attempts: Callable[[], int]


_handlers: dict[str, Handler] = {}


def handler(kind: str, *, max_attempts: Callable[[], int] | None = None,
            on_dead: Callable[[JobContext, str, bool], None] | None = None):
    """Register the function that runs jobs of `kind`."""
    def register(fn: Callable[[JobContext], None]) -> Callable[[JobContext], None]:
        _handlers[kind] = Handler(fn, on_dead, max_attempts or (lambda: get_settings().JOB_MAX_ATTEMPTS))
        return fn
    return register


def _ensure_handlers() -> None:
    from app.services import job_handlers  # noqa: F401  (registers the payment job kinds)


# ── Enqueue (inside the caller's transaction) ──

def enqueue(session: Session, kind: str, payload: dict[str, Any], *, request_id: str | None = None,
            dedupe_key: str | None = None, delay_seconds: float = 0) -> bool:
    """Add a job to the caller's transaction. Returns False if `dedupe_key` is already queued.
    Call `kick()` after the transaction commits for low latency."""
    _ensure_handlers()
    if kind not in _handlers:
        raise ValueError(f"Unknown job kind '{kind}'")
    if dedupe_key and session.scalar(select(Job.id).where(Job.dedupe_key == dedupe_key)):
        return False
    now = utcnow()
    job = Job(kind=kind, payload=payload, request_id=request_id, dedupe_key=dedupe_key,
              status=JobStatus.PENDING, attempts=0, max_attempts=_handlers[kind].max_attempts(),
              run_after=now + timedelta(seconds=delay_seconds), created_at=now, updated_at=now)
    try:
        with session.begin_nested():  # a concurrent duplicate must not roll back the caller
            session.add(job)
    except IntegrityError:
        return False
    return True


# ── Claim / run / finish ──

def _due(now: datetime):
    return or_(
        and_(Job.status == JobStatus.PENDING, Job.run_after <= now),
        and_(Job.status == JobStatus.RUNNING, Job.locked_until < now),  # worker died mid-job
    )


def claim(limit: int, now: datetime | None = None) -> list[JobContext]:
    now = now or utcnow()
    lease = timedelta(seconds=get_settings().JOB_LEASE_SECONDS)
    with session_scope() as session:
        ids = session.scalars(select(Job.id).where(_due(now)).order_by(Job.run_after, Job.id).limit(limit)).all()
    claimed: list[JobContext] = []
    for job_id in ids:
        with session_scope() as session:
            result = session.execute(
                update(Job).where(Job.id == job_id, _due(now))
                .values(status=JobStatus.RUNNING, locked_until=now + lease, attempts=Job.attempts + 1, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                continue  # another worker won it
            job = session.get(Job, job_id)
            claimed.append(JobContext(job.id, job.kind, dict(job.payload or {}), job.attempts, job.max_attempts,
                                      job.request_id))
    return claimed


def _backoff(attempt: int) -> float:
    s = get_settings()
    delay = min(s.JOB_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), s.JOB_BACKOFF_MAX_SECONDS)
    return delay * random.uniform(0.8, 1.2)


def _finish(ctx: JobContext, **values: Any) -> bool:
    """Record an outcome only if the job is still ours (fencing on the attempt number)."""
    with session_scope() as session:
        result = session.execute(
            update(Job).where(Job.id == ctx.id, Job.status == JobStatus.RUNNING, Job.attempts == ctx.attempt)
            .values(updated_at=utcnow(), locked_until=None, **values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


def execute(ctx: JobContext, now: datetime | None = None) -> str:
    """Run one claimed job and record DONE / retry / DEAD. Returns the outcome."""
    _ensure_handlers()
    handler_ = _handlers.get(ctx.kind)
    error, permanent = None, False
    if handler_ is None:
        error, permanent = f"No handler for job kind '{ctx.kind}'", True
    else:
        try:
            handler_.run(ctx)
        except PermanentFailure as exc:
            error, permanent = str(exc) or type(exc).__name__, True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]

    if error is None:
        _finish(ctx, status=JobStatus.DONE, finished_at=utcnow(), last_error=None)
        JOBS.labels(ctx.kind, "done").inc()
        return "done"

    if not permanent and not ctx.is_last_attempt:
        run_after = (now or utcnow()) + timedelta(seconds=_backoff(ctx.attempt))
        _finish(ctx, status=JobStatus.PENDING, run_after=run_after, last_error=error)
        JOBS.labels(ctx.kind, "retry").inc()
        logger.warning(f"Job {ctx.id} {ctx.kind} attempt {ctx.attempt}/{ctx.max_attempts} failed, "
                       f"retrying at {run_after:%H:%M:%S}: {error}")
        return "retry"

    if not _finish(ctx, status=JobStatus.DEAD, finished_at=utcnow(), last_error=error):
        return "superseded"
    JOBS.labels(ctx.kind, "dead").inc()
    logger.error(f"Job {ctx.id} {ctx.kind} dead after {ctx.attempt} attempt(s): {error}")
    with session_scope() as session:
        audit.record(session, "system", "JOB_DEAD", ctx.request_id, job_id=ctx.id, kind=ctx.kind,
                     attempts=ctx.attempt, error=error[:300], permanent=permanent)
    if handler_ is not None and handler_.on_dead is not None:
        try:
            handler_.on_dead(ctx, error, permanent)
        except Exception:
            logger.exception(f"on_dead hook for job {ctx.id} {ctx.kind} failed")
    return "dead"


def retry_dead(job_id: int, actor: str) -> Job | None:
    """Operator action: put a dead job back in the queue with a fresh set of attempts."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None or job.status != JobStatus.DEAD:
            return job
        now = utcnow()
        job.status, job.attempts, job.run_after, job.finished_at, job.updated_at = JobStatus.PENDING, 0, now, None, now
        audit.record(session, actor, "JOB_RETRIED", job.request_id, job_id=job.id, kind=job.kind)
    kick()
    with session_scope() as session:
        return session.get(Job, job_id)


# ── Running jobs ──

_drain_lock = threading.Lock()


def drain(now: datetime | None = None, max_jobs: int = 1000) -> int:
    """Run every due job synchronously (tests, CLI). New jobs made by handlers run too."""
    if not _drain_lock.acquire(blocking=False):
        return 0  # already draining further up the stack; that loop picks up new jobs
    ran = 0
    try:
        while ran < max_jobs:
            batch = claim(limit=20, now=now)
            if not batch:
                break
            for ctx in batch:
                execute(ctx, now=now)
                ran += 1
    finally:
        _drain_lock.release()
    return ran


class Worker:
    """Background worker thread: polls for due jobs and runs them on the task pool."""

    def __init__(self) -> None:
        concurrency = max(1, get_settings().JOB_CONCURRENCY)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._slots = threading.Semaphore(concurrency)
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="paytrust-job")

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="paytrust-jobs", daemon=True)
            self._thread.start()

    def stop(self, wait: bool = False) -> None:
        """Stop claiming. With wait=False, jobs still running finish in the background (one cut off
        by process exit keeps its lease and is retried by the next worker); wait=True blocks until
        they are done."""
        self._stop.set()
        self._wake.set()
        if wait and self._thread is not None:
            self._thread.join()
        self._pool.shutdown(wait=wait)

    def wake(self) -> None:
        self._wake.set()

    def _run(self, ctx: JobContext) -> None:
        try:
            execute(ctx)
        except Exception:
            logger.exception(f"Job {ctx.id} {ctx.kind} crashed the worker; its lease will expire and it retries")
        finally:
            self._slots.release()
            self._wake.set()  # a slot is free: look for more work now

    def _loop(self) -> None:
        poll = get_settings().JOB_POLL_SECONDS
        while not self._stop.is_set():
            self._wake.clear()
            try:
                free = 0
                while self._slots.acquire(blocking=False):
                    free += 1
                batch = claim(limit=free) if free else []
                for _ in range(free - len(batch)):
                    self._slots.release()
                for ctx in batch:
                    self._pool.submit(self._run, ctx)
            except Exception:
                logger.exception("Job worker loop failed; retrying")
            self._wake.wait(poll)


_worker: Worker | None = None


def start_worker() -> None:
    global _worker
    if _worker is None:
        _worker = Worker()
        _worker.start()


def stop_worker(wait: bool = False) -> None:
    global _worker
    if _worker is not None:
        _worker.stop(wait=wait)
        _worker = None


def kick() -> None:
    """New work was committed: run it now (inline mode) or wake the worker."""
    if tasks.is_inline():
        drain()
    elif _worker is not None:
        _worker.wake()
