"""Agent Arena: simulated agents exercise the real API and get scored against ground truth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_operator, require_role
from app.arena import runner
from app.arena.personas import PERSONAS, SCENARIOS
from app.db import get_session
from app.errors import NotFound
from app.models import ArenaRun, Operator, Role
from app.schemas import ArenaRunIn, ArenaRunOut

router = APIRouter(prefix="/v1/arena", tags=["arena"])


@router.get("/scenarios")
def scenarios(_: Operator = Depends(current_operator)):
    return {
        "scenarios": [{"key": k, "title": v["title"], "weights": v["weights"]} for k, v in SCENARIOS.items()],
        "personas": [p.__dict__ for p in PERSONAS.values()],
    }


@router.post("/runs", response_model=ArenaRunOut, status_code=202, summary="Start a simulation run")
def start(body: ArenaRunIn, operator: Operator = Depends(require_role(Role.REVIEWER))):
    return runner.start_run(body.scenario, body.requests, body.concurrency, operator.email)


@router.get("/runs", response_model=list[ArenaRunOut])
def runs(limit: int = Query(default=20, ge=1, le=100), _: Operator = Depends(current_operator),
         session: Session = Depends(get_session)):
    return session.scalars(select(ArenaRun).order_by(ArenaRun.started_at.desc()).limit(limit)).all()


@router.get("/runs/{run_id}", response_model=ArenaRunOut)
def run(run_id: str, _: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    found = session.get(ArenaRun, run_id)
    if found is None:
        raise NotFound("Arena run not found")
    return found
