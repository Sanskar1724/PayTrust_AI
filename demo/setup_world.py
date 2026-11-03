"""Build the demo database: team, agents + API keys, merchants, 40 users, their policies,
and the last 24 hours of agent traffic.

History is produced by PayTrust's own evaluation and approval code, so every stored
decision, risk factor and audit entry is exactly what the product would have produced.
Only this short-lived setup process moves PayTrust's clock to each historical moment;
the server the demo runs afterwards is untouched.

    python demo/setup_world.py            # normally called by run_demo.py
"""
from __future__ import annotations

import heapq
import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402
from common import BACKEND_DIR, DATA_DIR, DB_PATH, MOCK_URL, PAYTRUST_URL, WORLD_PATH, inr, paytrust_env, utf8_console  # noqa: E402

HISTORY_EVENTS = 260
IST = timezone(timedelta(hours=5, minutes=30))
# Relative activity by hour of day (IST): quiet nights, busy lunch and evenings.
HOUR_WEIGHTS = [0.15, 0.1, 0.08, 0.06, 0.06, 0.1, 0.3, 0.6, 0.9, 1.1, 1.2, 1.4,
                1.5, 1.4, 1.2, 1.1, 1.1, 1.2, 1.4, 1.6, 1.7, 1.5, 1.0, 0.5]


def _prepare_environment() -> None:
    os.environ.update(paytrust_env())
    # History must not call real LLM providers (hundreds of requests); the deterministic
    # explainer is used. The live server still uses any AI keys configured in .env.
    for key in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "REDIS_URL"):
        os.environ[key] = ""
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> None:
    utf8_console()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        sys.exit(f"{DB_PATH} already exists. run_demo.py --fresh deletes it first.")
    _prepare_environment()

    from app import db
    from app.errors import AppError
    from app.main import run_migrations
    from app.models import Agent, ApiKey, AuditEvent, Merchant, Operator, Payment, PaymentStatus, Policy, User
    from app.schemas import PaymentIn
    from app.services import approvals, evaluation, seed, tasks
    from app.services.security import generate_api_key, hash_password, new_webhook_secret
    from sqlalchemy import select, update

    print("Creating the demo database …")
    db.init_engine()
    run_migrations()
    with db.session_scope() as session:
        seed.bootstrap(session)  # the admin account (SEED_DEMO_DATA is off)

    world: dict = {"paytrust_url": PAYTRUST_URL, "mock_url": MOCK_URL,
                   "created_at": datetime.now(UTC).isoformat(),
                   "operators": {}, "agents": {}, "merchants": {}, "users": [], "policies": []}

    with db.session_scope() as session:
        for role_key, op in W.OPERATORS.items():
            session.add(Operator(email=op["email"], name=op["name"], role=op["role"],
                                 password_hash=hash_password(op["password"])))
            world["operators"][role_key] = {k: op[k] for k in ("email", "password", "name", "role")}

        for name, spec in W.AGENTS.items():
            agent = Agent(name=name, description=spec["description"], webhook_secret=new_webhook_secret())
            session.add(agent)
            session.flush()
            full_key, prefix, digest = generate_api_key()
            key = ApiKey(agent_id=agent.id, name="live-traffic", prefix=prefix, key_hash=digest)
            session.add(key)
            session.flush()
            world["agents"][name] = {"id": agent.id, "slug": spec["slug"], "key": full_key, "key_id": key.id,
                                     "key_prefix": prefix, "webhook_secret": agent.webhook_secret,
                                     "categories": spec["categories"],
                                     "callback_url": f"{MOCK_URL}/agent-inbox/{spec['slug']}"}

        for name, (category, tier, _) in W.MERCHANTS.items():
            merchant = Merchant(name=name, category=category, risk_tier=tier)
            session.add(merchant)
            session.flush()
            world["merchants"][name] = {"id": merchant.id, "category": category, "tier": tier}

        for u in W.build_users():
            user = User(**u)
            session.add(user)
            session.flush()
            world["users"].append({"id": user.id, "name": u["name"], "email": u["email"]})

        for p in W.build_policies([u["id"] for u in world["users"]]):
            agent_id = world["agents"][p["agent"]]["id"]
            fields = {k: v for k, v in p.items() if k not in ("agent",)}
            session.add(Policy(agent_id=agent_id, updated_by="demo-setup", **fields))
            world["policies"].append(p | {"agent_id": agent_id})

    print(f"  {len(world['users'])} users · {len(world['agents'])} agents · {len(world['merchants'])} merchants · "
          f"{len(world['policies'])} policies · {len(world['operators']) + 1} team members")

    # ── History: replay 24 hours of traffic through the real pipeline ──
    real_now = datetime.now(UTC)
    clock = [real_now]
    evaluation.utcnow = lambda: clock[0]
    approvals.utcnow = lambda: clock[0]
    tasks.run_inline(True)

    rng = random.Random(2026)
    start = real_now - timedelta(hours=24)
    times = []
    for _ in range(HISTORY_EVENTS):
        while True:
            t = start + timedelta(seconds=rng.uniform(0, 24 * 3600 - 300))
            if rng.random() < HOUR_WEIGHTS[t.astimezone(IST).hour] / max(HOUR_WEIGHTS):
                times.append(t)
                break

    queue: list[tuple[datetime, int, str, dict]] = []
    seq = 0
    for t in times:
        heapq.heappush(queue, (t, seq, "plan", {}))
        seq += 1

    def last_audit_id(session) -> int:
        return session.scalar(select(AuditEvent.id).order_by(AuditEvent.id.desc()).limit(1)) or 0

    def stamp(since_id: int, when: datetime, request_id: str | None = None) -> None:
        """Audit rows get wall-clock timestamps from the database default; move them to `when`."""
        with db.session_scope() as session:
            session.execute(update(AuditEvent).where(AuditEvent.id > since_id).values(created_at=when))
            if request_id:
                session.execute(update(Payment).where(Payment.request_id == request_id).values(updated_at=when))

    keys = {name: a for name, a in world["agents"].items()}
    counts = {"ALLOW": 0, "ASK_USER": 0, "DENY": 0}
    reviewer = W.OPERATORS["reviewer"]["email"]

    def send(planned: W.Planned, when: datetime, n: int) -> None:
        nonlocal seq
        agent = keys[planned.agent]
        rid = f"{agent['slug']}_{when.astimezone(IST):%m%d%H%M%S}_{rng.randrange(16**6):06x}"
        clock[0] = when
        with db.session_scope() as session:
            since = last_audit_id(session)
        req = PaymentIn(request_id=rid, **planned.payment)
        payment, _ = evaluation.evaluate_payment(req, key_agent_id=agent["id"], key_id=agent["key_id"],
                                                 source="api", actor=f"agent:{agent['id']}/key:{agent['key_prefix']}")
        stamp(since, when, rid)
        counts[payment.decision] += 1
        if payment.status == PaymentStatus.PENDING_APPROVAL:
            delay = timedelta(minutes=rng.uniform(2, 26))
            review_at = when + delay
            if rng.random() < 0.85 and review_at < real_now - timedelta(minutes=1):
                approve = rng.random() < (0.8 if planned.kind in ("honest", "big_ticket") else 0.1)
                heapq.heappush(queue, (review_at, seq, "review", {"rid": rid, "approve": approve}))
                seq += 1
        if planned.repeats > n + 1:
            heapq.heappush(queue, (when + timedelta(seconds=rng.uniform(8, 40)), seq, "repeat",
                                   {"planned": planned, "n": n + 1}))
            seq += 1

    while queue:
        when, _, action, data = heapq.heappop(queue)
        clock[0] = when
        with db.session_scope() as session:
            since = last_audit_id(session)
        approvals.expire_due()  # pending approvals nobody handled in 30 minutes
        stamp(since, when)
        if action == "plan":
            send(W.next_payment(rng, world), when, 0)
        elif action == "repeat":
            send(data["planned"], when, data["n"])
        elif action == "review":
            with db.session_scope() as session:
                since = last_audit_id(session)
            note = ("User confirmed on the phone" if data["approve"] else "User did not recognise this purchase")
            try:
                approvals.review(data["rid"], data["approve"], reviewer, note)
            except AppError:
                pass  # expired or blocked in the meantime; the audit trail says which
            stamp(since, when, data["rid"])

    # Back to the real clock for anything left.
    clock[0] = datetime.now(UTC)
    with db.session_scope() as session:
        for a in world["agents"].values():
            session.get(Agent, a["id"]).callback_url = a["callback_url"]
        pending = session.scalar(select(Payment.id).where(Payment.status == PaymentStatus.PENDING_APPROVAL).limit(1))

    WORLD_PATH.write_text(json.dumps(world, indent=2), encoding="utf-8")
    total = sum(counts.values())
    with db.session_scope() as session:
        approved = sum(p.amount for p in session.scalars(
            select(Payment).where(Payment.status.in_(PaymentStatus.SUCCESSFUL))))
    print(f"  24 h of history: {total} payments · ALLOW {counts['ALLOW']} · ASK_USER {counts['ASK_USER']} · "
          f"DENY {counts['DENY']} · {inr(approved)} approved"
          + (" · some approvals still waiting" if pending else ""))
    print(f"World written to {WORLD_PATH}")


if __name__ == "__main__":
    main()
