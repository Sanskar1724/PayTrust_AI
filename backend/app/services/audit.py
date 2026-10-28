"""Append-only audit trail. Written in the same transaction as the change it records."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.log import get_request_id
from app.models import AuditEvent


def record(session: Session, actor: str, event_type: str, request_id: str | None = None,
           **data: Any) -> AuditEvent:
    event = AuditEvent(
        actor=actor[:254],
        event_type=event_type,
        request_id=request_id,
        data={**data, "trace_id": get_request_id()},
    )
    session.add(event)
    return event
