"""Dashboard metrics computed from the payments table."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Payment, PaymentStatus

WINDOW_HOURS = 24
MAX_ROWS = 20_000


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def dashboard(session: Session) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(hours=WINDOW_HOURS)
    rows = session.execute(
        select(Payment.created_at, Payment.decision, Payment.status, Payment.amount,
               Payment.processing_ms, Payment.policy_result, Payment.risk_result)
        .where(Payment.created_at >= since, Payment.source != "arena")
        .order_by(Payment.created_at.desc())
        .limit(MAX_ROWS)
    ).all()

    decisions = Counter(r.decision for r in rows)
    violations: Counter[str] = Counter()
    factors: Counter[str] = Counter()
    for r in rows:
        violations.update((r.policy_result or {}).get("violations") or [])
        factors.update({f["name"] for f in (r.risk_result or {}).get("factors") or []})

    buckets: dict[str, dict[str, int]] = {}
    for h in range(WINDOW_HOURS, -1, -1):
        key = (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:00:00Z")
        buckets[key] = {"ALLOW": 0, "ASK_USER": 0, "DENY": 0}
    for r in rows:
        key = r.created_at.strftime("%Y-%m-%dT%H:00:00Z")
        if key in buckets:
            buckets[key][r.decision] += 1

    pending = session.scalar(
        select(func.count()).select_from(Payment).where(
            Payment.status == PaymentStatus.PENDING_APPROVAL, Payment.source != "arena")
    )
    latencies = [r.processing_ms for r in rows]
    return {
        "window_hours": WINDOW_HOURS,
        "total": len(rows),
        "decisions": {d: decisions.get(d, 0) for d in ("ALLOW", "ASK_USER", "DENY")},
        "pending_approvals": int(pending or 0),
        "amount_approved": sum(r.amount for r in rows if r.status in PaymentStatus.SUCCESSFUL),
        "amount_blocked": sum(r.amount for r in rows if r.status in (PaymentStatus.DENIED, PaymentStatus.REJECTED)),
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95),
                       "p99": _percentile(latencies, 99)},
        "top_violations": violations.most_common(6),
        "top_factors": factors.most_common(6),
        "series": [{"hour": k, **v} for k, v in buckets.items()],
    }
