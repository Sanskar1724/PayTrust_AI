"""Agent Arena runner: provision payers + an agent key, fire every persona's requests at the
real HTTP API, and score the decisions against each request's ground truth."""
from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select, update

from app.api.deps import ARENA_KEY_PREFIX
from app.arena.personas import ARENA_MERCHANTS, PERSONAS, SCENARIOS, STANDARD_POLICY, Stream, build_streams
from app.config import get_settings
from app.db import session_scope, utcnow
from app.errors import Conflict, ValidationFailed
from app.log import get_logger
from app.models import Agent, ApiKey, ArenaRun, Merchant, Payment, PaymentStatus, Policy, User
from app.services import audit
from app.services.events import bus
from app.services.security import generate_api_key, new_webhook_secret

logger = get_logger("arena")
ARENA_AGENT = "Arena Agent"
ROGUE_AGENT = "Arena Rogue Agent"
PROGRESS_EVERY = 10


def _default_client() -> httpx.Client:
    return httpx.Client(base_url=get_settings().ARENA_BASE_URL, timeout=30.0)


# Tests swap this for FastAPI's TestClient so runs execute in-process.
client_factory: Callable[[], Any] = _default_client


@dataclass
class Fixtures:
    api_keys: list[str]  # one key per stream: each simulated agent instance has its own credential
    key_ids: list[int]
    agent_id: int
    rogue_agent_id: int
    merchant_ids: dict[str, int]
    stream_users: list[int]
    no_policy_user: int


def _get_or_create_agent(session, name: str, description: str) -> Agent:
    agent = session.scalar(select(Agent).where(Agent.name == name))
    if agent is None:
        agent = Agent(name=name, description=description, webhook_secret=new_webhook_secret())
        session.add(agent)
        session.flush()
    agent.is_active = True
    return agent


def provision(run_id: str, streams: list[Stream]) -> Fixtures:
    tag = run_id[:8]
    with session_scope() as session:
        merchant_ids: dict[str, int] = {}
        for name, (category, tier) in ARENA_MERCHANTS.items():
            merchant = session.scalar(select(Merchant).where(Merchant.name == name).order_by(Merchant.id))
            if merchant is None:
                merchant = Merchant(name=name, category=category, risk_tier=tier)
                session.add(merchant)
                session.flush()
            merchant_ids[name] = merchant.id

        agent = _get_or_create_agent(session, ARENA_AGENT, "Simulated agent used by the Agent Arena")
        rogue = _get_or_create_agent(session, ROGUE_AGENT, "Identity a stolen key tries to impersonate")

        users = []
        for i, stream in enumerate(streams):
            user = User(name=f"Arena · {PERSONAS[stream.persona].title} #{i + 1}", external_ref=f"arena:{tag}:{i}")
            session.add(user)
            users.append(user)
        stranger = User(name="Arena · Payer without mandate", external_ref=f"arena:{tag}:stranger")
        session.add(stranger)
        session.flush()
        session.add_all(Policy(user_id=u.id, agent_id=agent.id, updated_by="arena", **STANDARD_POLICY) for u in users)

        keys: list[tuple[str, ApiKey]] = []
        for i in range(len(streams)):
            full_key, prefix, digest = generate_api_key()
            key = ApiKey(agent_id=agent.id, name=f"{ARENA_KEY_PREFIX}{tag}-{i}", prefix=prefix, key_hash=digest)
            session.add(key)
            keys.append((full_key, key))
        session.flush()
        return Fixtures([k for k, _ in keys], [row.id for _, row in keys], agent.id, rogue.id, merchant_ids,
                        [u.id for u in users], stranger.id)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))], 2)


def score(results: list[dict[str, Any]], elapsed: float, planned: int) -> dict[str, Any]:
    ok = [r for r in results if r["decision"]]
    malicious = [r for r in ok if r["intent"] == "malicious"]
    legit = [r for r in ok if r["intent"] == "legit"]
    per_persona: dict[str, dict[str, Any]] = defaultdict(lambda: {"requests": 0, "correct": 0, "decisions": Counter()})
    for r in results:
        row = per_persona[r["persona"]]
        row["requests"] += 1
        row["correct"] += int(r["correct"])
        row["decisions"][r["decision"] or "ERROR"] += 1
    return {
        "planned": planned,
        "completed": len(results),
        "errors": len(results) - len(ok),
        "correct": sum(r["correct"] for r in results),
        "accuracy": round(sum(r["correct"] for r in results) / len(results), 4) if results else 0.0,
        "malicious": {
            "total": len(malicious),
            "caught": sum(r["decision"] != "ALLOW" for r in malicious),
            "missed": sum(r["decision"] == "ALLOW" for r in malicious),
        },
        "legit": {
            "total": len(legit),
            "blocked": sum(r["decision"] == "DENY" for r in legit),
            "asked": sum(r["decision"] == "ASK_USER" and "ASK_USER" not in r["expected"] for r in legit),
            "allowed": sum(r["decision"] == "ALLOW" for r in legit),
        },
        "decisions": dict(Counter(r["decision"] or "ERROR" for r in results)),
        "personas": {
            k: {"title": PERSONAS[k].title, "intent": PERSONAS[k].intent, "expectation": PERSONAS[k].expectation,
                "requests": v["requests"], "correct": v["correct"], "decisions": dict(v["decisions"])}
            for k, v in per_persona.items()
        },
        "latency_ms": {
            "client_p50": _percentile([r["latency_ms"] for r in results], 50),
            "client_p95": _percentile([r["latency_ms"] for r in results], 95),
            "client_p99": _percentile([r["latency_ms"] for r in results], 99),
            "server_p50": _percentile([r["server_ms"] for r in ok], 50),
            "server_p95": _percentile([r["server_ms"] for r in ok], 95),
        },
        "elapsed_seconds": round(elapsed, 2),
        "throughput_rps": round(len(results) / elapsed, 2) if elapsed else 0.0,
        "mistakes": [
            {k: r[k] for k in ("persona", "request_id", "decision", "status_code")} | {"expected": sorted(r["expected"])}
            for r in results if not r["correct"]
        ][:20],
    }


def execute(run_id: str, streams: list[Stream], fx: Fixtures, concurrency: int,
            on_progress: Callable[[list[dict[str, Any]]], None] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    tag = run_id[:8]

    def run_stream(index: int, stream: Stream) -> None:
        client = client_factory()
        try:
            for n, step in enumerate(stream.steps):
                body = {
                    "request_id": f"arena_{tag}_{index}_{n}",
                    "user_id": fx.no_policy_user if step.no_policy_user else fx.stream_users[index],
                    "merchant_id": fx.merchant_ids[step.payment["merchant"]],
                    "merchant_name": step.payment["merchant"],
                    "amount": step.payment["amount"],
                    "category": step.payment["category"],
                    "description": step.payment["description"],
                    "agent_reason": step.payment["agent_reason"],
                }
                if step.use_rogue_agent_id:
                    body["agent_id"] = fx.rogue_agent_id
                started = time.perf_counter()
                decision, server_ms, code = None, 0.0, 0
                try:
                    resp = client.post("/v1/payments", json=body, headers={"X-API-Key": fx.api_keys[index]})
                    code = resp.status_code
                    if code < 300:
                        data = resp.json()
                        decision, server_ms = data["decision"], float(data.get("processing_ms") or 0)
                except Exception as exc:
                    logger.warning(f"Arena request {body['request_id']} failed: {exc}")
                result = {
                    "persona": step.persona, "intent": step.intent, "expected": step.expected,
                    "request_id": body["request_id"], "decision": decision, "status_code": code,
                    "correct": decision in step.expected,
                    "latency_ms": (time.perf_counter() - started) * 1000, "server_ms": server_ms,
                }
                with lock:
                    results.append(result)
                    snapshot = list(results) if on_progress and len(results) % PROGRESS_EVERY == 0 else None
                if snapshot is not None:
                    on_progress(snapshot)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="arena") as pool:
        for future in [pool.submit(run_stream, i, s) for i, s in enumerate(streams)]:
            future.result()
    return results


def start_run(scenario: str, requests: int, concurrency: int, actor: str, seed: int | None = None,
              background: bool = True) -> ArenaRun:
    if scenario not in SCENARIOS:
        raise ValidationFailed(f"Unknown scenario '{scenario}'. Choose from {sorted(SCENARIOS)}")
    with session_scope() as session:
        if session.scalar(select(ArenaRun.id).where(ArenaRun.status == "RUNNING")):
            raise Conflict("An Arena run is already in progress")
        run = ArenaRun(scenario=scenario, started_by=actor,
                       params={"requests": requests, "concurrency": concurrency, "seed": seed})
        session.add(run)
        session.flush()
        run_id = run.id
    if background:
        threading.Thread(target=_run, args=(run_id, scenario, requests, concurrency, seed),
                         name=f"arena-{run_id[:8]}", daemon=True).start()
    else:
        _run(run_id, scenario, requests, concurrency, seed)
    with session_scope() as session:
        return session.get(ArenaRun, run_id)


def _save(run_id: str, **fields: Any) -> None:
    with session_scope() as session:
        run = session.get(ArenaRun, run_id)
        for k, v in fields.items():
            setattr(run, k, v)


def _run(run_id: str, scenario: str, requests: int, concurrency: int, seed: int | None) -> None:
    fixtures: Fixtures | None = None
    streams = build_streams(scenario, requests, seed)
    planned = sum(len(s.steps) for s in streams)
    started = time.perf_counter()

    def progress(snapshot: list[dict[str, Any]]) -> None:
        stats = score(snapshot, time.perf_counter() - started, planned)
        _save(run_id, stats=stats)
        bus.publish("arena.progress", {"id": run_id, "status": "RUNNING", "stats": stats})

    try:
        fixtures = provision(run_id, streams)
        results = execute(run_id, streams, fixtures, concurrency, progress)
        stats = score(results, time.perf_counter() - started, planned)
        _save(run_id, status="COMPLETED", stats=stats, finished_at=utcnow())
        bus.publish("arena.progress", {"id": run_id, "status": "COMPLETED", "stats": stats})
        logger.info(f"Arena run {run_id[:8]} done: accuracy={stats['accuracy']} rps={stats['throughput_rps']}")
    except Exception as exc:
        logger.exception(f"Arena run {run_id[:8]} failed")
        _save(run_id, status="FAILED", error=str(exc)[:500], finished_at=utcnow())
        bus.publish("arena.progress", {"id": run_id, "status": "FAILED", "error": str(exc)[:200]})
    finally:
        if fixtures is not None:
            cleanup(run_id, fixtures)


def cleanup(run_id: str, fx: Fixtures) -> None:
    """Revoke the run's keys and close its pending approvals, so simulations never reach a human's inbox."""
    tag = run_id[:8]
    with session_scope() as session:
        session.execute(update(ApiKey).where(ApiKey.id.in_(fx.key_ids)).values(revoked_at=utcnow()))
        pending = session.scalars(select(Payment).where(
            Payment.request_id.startswith(f"arena_{tag}_", autoescape=True), Payment.status == PaymentStatus.PENDING_APPROVAL)).all()
        for payment in pending:
            payment.status = PaymentStatus.EXPIRED
            payment.review_note = "Closed automatically at the end of an Agent Arena run"
        if pending:
            audit.record(session, "arena", "ARENA_CLEANUP", None, run_id=run_id, closed=len(pending))


def fail_interrupted_runs() -> None:
    """A restart kills in-flight runs; mark them so a new run can start."""
    with session_scope() as session:
        session.execute(update(ArenaRun).where(ArenaRun.status == "RUNNING")
                        .values(status="FAILED", error="Interrupted by server restart", finished_at=utcnow()))
