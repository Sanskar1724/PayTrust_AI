"""AI provider fallback / circuit breaker, and an end-to-end Agent Arena run."""
from __future__ import annotations

from app.arena import runner
from app.arena.personas import SCENARIOS, build_streams
from app.services.ai import Investigator, Provider, parse_response

FACTS = {"policy_result": {"violations": []}, "risk_result": {"risk_level": "LOW", "risk_score": 5, "factors": []},
         "decision": {"decision": "ALLOW"}}


class Fake(Provider):
    def __init__(self, name, reply=None, error=None):
        super().__init__("fake-model")
        self.name, self.reply, self.error, self.calls = name, reply, error, 0

    def complete(self, prompt):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.reply


GOOD = '```json\n{"explanation": "Low risk.", "summary": "ok", "concerns": [], "review_questions": ["q"], "confidence": 1.4}\n```'


def test_parse_response_strips_fences_and_clamps():
    out = parse_response(GOOD)
    assert out["explanation"] == "Low risk." and out["confidence"] == 1.0


def test_falls_back_to_next_provider_then_deterministic():
    first, second = Fake("a", error="boom"), Fake("b", reply=GOOD)
    result = Investigator([first, second]).investigate(FACTS)
    assert result["provider"] == "b" and result["fallback_used"] and result["errors"]

    broken = Investigator([Fake("a", reply="not json"), Fake("b", error="down")]).investigate(FACTS)
    assert broken["provider"] == "deterministic" and broken["advisory_only"]


def test_circuit_breaker_opens_after_repeated_failures():
    flaky = Fake("flaky", error="timeout")
    inv = Investigator([flaky])
    for _ in range(5):
        inv.investigate(FACTS)
    assert flaky.calls == flaky.breaker.threshold  # later calls skipped while open


def test_scenarios_build_expected_sizes():
    for key in SCENARIOS:
        streams = build_streams(key, 40, seed=1)
        assert 30 <= sum(len(s.steps) for s in streams) <= 60


def test_arena_mixed_run_scores_perfectly(client, admin_headers):
    run = runner.start_run("mixed", requests=80, concurrency=4, actor="tests", seed=7, background=False)
    assert run.status == "COMPLETED", run.error
    stats = run.stats
    assert stats["errors"] == 0
    assert stats["malicious"]["missed"] == 0, stats["mistakes"]
    assert stats["legit"]["blocked"] == 0, stats["mistakes"]
    assert stats["accuracy"] == 1.0, stats["mistakes"]

    listed = client.get("/v1/arena/runs", headers=admin_headers).json()
    assert listed[0]["id"] == run.id
    # The Arena's own key is revoked after the run.
    agents = client.get("/v1/agents", headers=admin_headers).json()
    arena = next(a for a in agents if a["name"] == runner.ARENA_AGENT)
    assert all(k["revoked_at"] for k in arena["keys"])
    # Simulation traffic never reaches the reviewer inbox or the dashboard.
    assert client.get("/v1/payments?status=PENDING_APPROVAL&include_arena=true", headers=admin_headers).json()["total"] == 0
    assert client.get("/v1/stats", headers=admin_headers).json()["total"] == 0
    assert stats["personas"]["budget_drain"]["decisions"].get("DENY", 0) + stats["personas"]["budget_drain"]["decisions"].get("ASK_USER", 0) > 0
    # Arena payers are hidden from the default user list.
    assert all(not (u["external_ref"] or "").startswith("arena:") for u in client.get("/v1/users", headers=admin_headers).json())
