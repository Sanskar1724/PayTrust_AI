"""
core/metrics.py — Phase 15 Observability metrics.

Queries SQLite for dashboard stats. No secrets. Fast.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from database.database import get_connection

def get_dashboard_metrics(db_path: Path | None = None) -> dict[str, Any]:
    try:
        conn = get_connection(db_path)
    except Exception:
        # No DB yet (fresh clone) — dashboard shows zeros instead of crashing.
        return {
            "total_requests": 0, "total_decisions": 0, "by_decision": {},
            "avg_risk": 0.0, "max_risk": 0, "high_risk_count": 0,
            "policy_violations": 0, "ai_failures": 0,
            "razorpay_events": {"total": 0, "processed": 0},
        }
    try:
        cur = conn.cursor()
        # Totals
        cur.execute("SELECT COUNT(*) FROM payment_requests")
        total_requests = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM decisions")
        total_decisions = cur.fetchone()[0]
        cur.execute("SELECT decision, COUNT(*) as c FROM decisions GROUP BY decision")
        by_decision = {r["decision"]: r["c"] for r in cur.fetchall()}
        cur.execute("SELECT AVG(risk_score) as avg_risk, MAX(risk_score) as max_risk FROM decisions")
        row = cur.fetchone()
        avg_risk = row["avg_risk"]
        max_risk = row["max_risk"]
        cur.execute("SELECT COUNT(*) FROM decisions WHERE risk_level IN ('HIGH','CRITICAL')")
        high_risk = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM decisions WHERE json_extract(policy_result, '$.violations') != '[]' AND json_extract(policy_result, '$.violations') IS NOT NULL")
        # Fallback if json_extract not available or violations stored differently — count where policy_result contains violation
        try:
            cur.execute("SELECT COUNT(*) FROM decisions WHERE policy_result LIKE '%violations%' AND policy_result NOT LIKE '%\"violations\": []%'")
            violations = cur.fetchone()[0]
        except Exception:
            violations = 0
        # AI failures — audit_logs where event_type AI and action error? We track via determinations: use audit_logs where action = AI_ERROR
        cur.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type = 'AI_INVESTIGATION' AND action = 'ERROR'")
        ai_failures = cur.fetchone()[0] if cur else 0
        # Razorpay events
        try:
            cur.execute("SELECT COUNT(*) FROM razorpay_events")
            razor_total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM razorpay_events WHERE status = 'PROCESSED'")
            razor_processed = cur.fetchone()[0]
        except Exception:
            razor_total = 0
            razor_processed = 0

        return {
            "total_requests": total_requests,
            "total_decisions": total_decisions,
            "by_decision": by_decision,
            "avg_risk": float(avg_risk) if avg_risk is not None else 0.0,
            "max_risk": int(max_risk) if max_risk is not None else 0,
            "high_risk_count": high_risk,
            "policy_violations": violations,
            "ai_failures": ai_failures,
            "razorpay_events": {"total": razor_total, "processed": razor_processed},
        }
    finally:
        conn.close()

def log_evaluation(request_id: str, decision: str, risk_score: int, risk_level: str, processing_ms: float, has_error: bool = False):
    """
    Structured log for observability — never logs secrets.
    """
    from core.logger import get_logger, get_request_id
    import logging
    logger = get_logger("observability")
    logger.info(
        f"EVALUATION request_id={request_id} decision={decision} risk={risk_score} level={risk_level} ms={processing_ms:.1f} err={has_error} req={get_request_id()}"
    )
