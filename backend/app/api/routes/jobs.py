"""Background jobs: the outbox and its dead-letter queue (operators)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_operator, require_role
from app.db import get_session, session_scope
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import Job, JobStatus, Operator, Role
from app.schemas import JobOut, Page
from app.services import jobs

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("", response_model=Page, summary="List background jobs (newest first)")
def list_jobs(
    status: str | None = Query(default=None, description="PENDING, RUNNING, DONE or DEAD"),
    kind: str | None = None,
    request_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Operator = Depends(current_operator),
    session: Session = Depends(get_session),
):
    stmt = select(Job)
    if status:
        if status.upper() not in JobStatus.ALL:
            raise ValidationFailed(f"status must be one of {JobStatus.ALL}")
        stmt = stmt.where(Job.status == status.upper())
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if request_id:
        stmt = stmt.where(Job.request_id == request_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(Job.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=[JobOut.model_validate(r) for r in rows], total=total or 0, limit=limit, offset=offset)


@router.get("/summary", summary="Job counts by status and kind")
def summary(_: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    rows = session.execute(select(Job.status, Job.kind, func.count()).group_by(Job.status, Job.kind)).all()
    by_status = {s: 0 for s in JobStatus.ALL}
    by_kind: dict[str, dict[str, int]] = {}
    for status, kind, count in rows:
        by_status[status] = by_status.get(status, 0) + count
        by_kind.setdefault(kind, {s: 0 for s in JobStatus.ALL})[status] = count
    oldest = session.scalar(select(func.min(Job.created_at)).where(Job.status == JobStatus.PENDING))
    return {"by_status": by_status, "by_kind": by_kind, "oldest_pending_at": oldest}


@router.post("/{job_id}/retry", response_model=JobOut, summary="Retry a dead job (admins)")
def retry(job_id: int, operator: Operator = Depends(require_role(Role.ADMIN))):
    # Own short transaction: on SQLite a request-scoped session would hold the write lock retry_dead needs.
    with session_scope() as session:
        current = session.get(Job, job_id)
        status = current.status if current else None
    if status is None:
        raise NotFound("Job not found")
    if status != JobStatus.DEAD:
        raise Conflict(f"Only dead jobs can be retried; this one is {status}")
    job = jobs.retry_dead(job_id, f"operator:{operator.email}")
    if job.status == JobStatus.DEAD:
        raise Conflict("The job is still dead (its retry failed immediately)")
    return JobOut.model_validate(job)
