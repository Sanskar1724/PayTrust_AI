"""api/service.py — HTTP service functions over the tested PayTrust engines.

Pure functions (no FastAPI imports) → unit-testable like the rest of the codebase.
Mirrors the exact pipeline + persistence of `app.py`:
  PaymentRequest → create_payment_request → PolicyEngine → RiskEngine →
  DecisionEngine → persist(risk_assessments, decisions, audit_logs) →
  DecisionSimulator → (optional advisory AIEngine).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger, get_request_id
from core.metrics import log_evaluation
from database import repositories as repo
from database.database import get_connection
from engines.ai_engine import AIEngine, build_facts
from engines.decision_engine import DecisionEngine
from engines.decision_simulator import simulate
from engines.policy_engine import PolicyEngine
from engines.risk_engine import RiskEngine
from models.payment_request import PaymentRequest

logger = get_logger("api.service")


def _engines() -> tuple[PolicyEngine, RiskEngine, DecisionEngine]:
    pe = PolicyEngine()
    re = RiskEngine()
    return pe, re, DecisionEngine(pe, re)


def evaluate_payment(
    payload: dict[str, Any],
    db_path: Path | None = None,
    investigate: bool = False,
) -> dict[str, Any]:
    """Run the full deterministic pipeline for one payment and return the decision.

    Idempotency: if `request_id` already exists, we skip re-creating the payment
    (UNIQUE constraint) and re-evaluate deterministically — same input + same
    state ⇒ same decision, so safe to retry.
    """
    t0 = time.perf_counter()
    body = dict(payload)
    with_ai = bool(body.pop("investigate", False)) or investigate

    # 1. Validate (Pydantic — raises ValidationError on bad input → mapped to 422)
    pr = PaymentRequest(**body)
    pay_dict = pr.to_db_dict()
    existing = repo.get_payment_request(pr.request_id, db_path=db_path)

    # 2. Persist the payment request (skip if already present — idempotent)
    if existing is None:
        repo.create_payment_request(**pay_dict, db_path=db_path)

    # 3. Deterministic engines (DB-backed: daily spend, frequency, merchant history)
    pe, re, de = _engines()
    pol = pe.evaluate_request(
        pr.user_id, pr.agent_id, pr.amount, pr.category,
        merchant_id=pr.merchant_id, merchant_name=pr.merchant_name,
        db_path=db_path,
    )
    risk = re.assess_request(
        pr.user_id, pr.agent_id,
        {
            "amount": pr.amount,
            "category": pr.category,
            "merchant_id": pr.merchant_id,
            "merchant_name": pr.merchant_name,
        },
        pol,
        db_path=db_path,
    )
    dec = de.decide(pol, risk)
    ms = (time.perf_counter() - t0) * 1000

    # 4. Persist risk + decision + audit (same writes as app.py — parameterized)
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO risk_assessments (request_id, risk_score, risk_level, factors) VALUES (?,?,?,?)",
            (pr.request_id, risk["risk_score"], risk["risk_level"], json.dumps(risk["factors"])),
        )
        cur.execute(
            "INSERT OR REPLACE INTO decisions (request_id, decision, risk_score, risk_level, policy_result, reasons) VALUES (?,?,?,?,?,?)",
            (pr.request_id, dec["decision"], dec["risk_score"], dec["risk_level"], json.dumps(pol), json.dumps(dec["reasons"])),
        )
        cur.execute(
            "INSERT INTO audit_logs (request_id, event_type, actor, action, metadata) VALUES (?,?,?,?,?)",
            (
                pr.request_id,
                "PAYMENT_EVALUATED",
                f"api:{get_request_id()[:12]}",
                dec["decision"],
                json.dumps({"amount": pr.amount, "risk_score": risk["risk_score"], "ms": round(ms, 1)}),
            ),
        )
        conn.commit()

    log_evaluation(pr.request_id, dec["decision"], dec["risk_score"], dec["risk_level"], ms)

    # 5. Counterfactual simulator (SIMULATED costs)
    sim = simulate(pay_dict, pol, risk, dec)

    # 6. Optional advisory AI investigation (deterministic fallback when offline)
    ai_res = None
    if with_ai:
        facts = build_facts(pay_dict, pol, risk, dec)
        ai_res = AIEngine().investigate(facts)

    return {
        "request_id": pr.request_id,
        "decision": dec["decision"],
        "risk_score": dec["risk_score"],
        "risk_level": dec["risk_level"],
        "reasons": dec["reasons"],
        "requires_approval": dec["requires_approval"],
        "policy_result": pol,
        "risk_result": risk,
        "simulation": sim,
        "ai": ai_res,
        "processing_ms": round(ms, 1),
        "duplicate": existing is not None,
        "simulated_estimates": True,
    }

def list_payments(limit: int = 50, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Recent requests with their decision (same join as app.py `_recent_requests`)."""
    limit = max(1, min(limit, 500))
    return repo.fetch_all(
        """
        SELECT pr.request_id, pr.amount, pr.category, pr.merchant_name, pr.created_at,
               pr.user_id, pr.agent_id, pr.merchant_id, pr.status,
               d.decision, d.risk_score, d.risk_level
        FROM payment_requests pr LEFT JOIN decisions d ON d.request_id = pr.request_id
        ORDER BY pr.created_at DESC LIMIT ?
        """,
        (limit,),
        db_path=db_path,
    )


def get_payment_detail(request_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Full detail for one request: payment + decision + risk assessment."""
    row = repo.get_payment_request(request_id, db_path=db_path)
    if not row:
        return None
    dec = repo.fetch_one("SELECT * FROM decisions WHERE request_id = ?", (request_id,), db_path=db_path)
    risk = repo.fetch_one("SELECT * FROM risk_assessments WHERE request_id = ?", (request_id,), db_path=db_path)
    audit = repo.fetch_all(
        "SELECT request_id, event_type, actor, action, created_at FROM audit_logs WHERE request_id = ? ORDER BY created_at DESC",
        (request_id,),
        db_path=db_path,
    )
    return {"payment": row, "decision": dec, "risk_assessment": risk, "audit": audit}


def get_evaluation_reports(base: Path | None = None) -> dict[str, Any]:
    """Honest evaluation results — IEEE held-out test + synthetic demo sets.

    Never invented: reads only actual report files committed with the models.
    """
    root = base or Path(__file__).resolve().parents[1]
    ieee = root / "evaluation" / "ieee_report.json"
    ml = root / "evaluation" / "ml_report.json"
    ieee_data = json.loads(ieee.read_text(encoding="utf-8")) if ieee.exists() else None
    ml_data = json.loads(ml.read_text(encoding="utf-8")) if ml.exists() else None
    return {
        "ieee": ieee_data,
        "synthetic_ml": ml_data,
        "available": ieee_data is not None or ml_data is not None,
        "disclaimer": (
            "IEEE model evaluated on a held-out IEEE-CIS test set (real data). "
            "Synthetic ML was trained on generated demo data — NOT a claim of production performance. "
            "Never treat synthetic numbers as real fraud rates."
        ),
    }