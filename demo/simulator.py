"""Live traffic: AI agents keep shopping for their users through PayTrust's public API,
with the occasional attack mixed in, and a reviewer works through the approvals inbox.

Every request is a real HTTP call with the agent's own API key, exactly what an
integration would send. Nothing here talks to the database.

    python demo/simulator.py                  # normally started by run_demo.py
    python demo/simulator.py --count 20       # send 20 payments and stop
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402
from common import C, decision_label, inr, load_world, utf8_console  # noqa: E402

KIND_LABEL = {
    "honest": "",
    "big_ticket": f"{C.CYAN}big purchase{C.RESET}",
    "loop": f"{C.MAGENTA}⚠ runaway loop{C.RESET}",
    "injection": f"{C.MAGENTA}⚠ prompt injection{C.RESET}",
    "spoof": f"{C.MAGENTA}⚠ fake merchant name{C.RESET}",
    "stolen_key": f"{C.MAGENTA}⚠ stolen key{C.RESET}",
}
_print_lock = threading.Lock()


def say(line: str) -> None:
    with _print_lock:
        print(line, flush=True)


def stamp() -> str:
    return f"{C.DIM}{datetime.now():%H:%M:%S}{C.RESET}"


def _verdict(planned: W.Planned, attempt: int, decision: str) -> str:
    if planned.kind == "honest" or (planned.kind == "loop" and attempt == 0):
        return ""  # an ordinary purchase (or the first, legitimate-looking buy of a loop)
    expect = ("ASK_USER", "DENY") if planned.kind == "loop" else planned.expect
    if decision not in expect:
        return f" {C.RED}✗ expected {'/'.join(expect)}{C.RESET}"
    return f" {C.GREEN}✓ sent to a human{C.RESET}" if planned.kind == "big_ticket" else f" {C.GREEN}✓ caught{C.RESET}"


def send_payment(http: httpx.Client, world: dict, planned: W.Planned, users: dict[int, str],
                 attempt: int = 0) -> dict | None:
    agent = world["agents"][planned.agent]
    body = {"request_id": f"{agent['slug']}-{uuid.uuid4().hex[:12]}", **planned.payment}
    try:
        resp = http.post("/v1/payments", json=body, headers={"X-API-Key": agent["key"]})
    except httpx.HTTPError as exc:
        say(f"{stamp()} {C.RED}PayTrust unreachable: {exc}{C.RESET}")
        return None
    if resp.status_code not in (200, 201):
        say(f"{stamp()} {C.RED}HTTP {resp.status_code}{C.RESET} {resp.text[:160]}")
        return None
    p = resp.json()
    who = users.get(p["user_id"], f"user {p['user_id']}")
    shown_merchant = p["merchant_name"]
    if planned.payment["merchant_name"] != shown_merchant:
        shown_merchant += f" {C.DIM}(agent said '{planned.payment['merchant_name']}'){C.RESET}"
    verdict = _verdict(planned, attempt, p["decision"])
    label = KIND_LABEL[planned.kind] + (f" #{attempt + 1}" if planned.kind == "loop" else "")
    reason = (p["reasons"] or [""])[0]
    say(f"{stamp()} {decision_label(p['decision'])} {inr(p['amount']):>10}  {planned.agent:<12} "
        f"{who:<18} → {shown_merchant}  {label}{verdict}\n"
        f"{'':9}{C.DIM}{p.get('description') or ''} · {reason}{C.RESET}")
    return p


def traffic(world: dict, rate: tuple[float, float], count: int | None, seed: int | None, stop: threading.Event) -> None:
    rng = random.Random(seed)
    users = {u["id"]: u["name"] for u in world["users"]}
    sent = 0
    with httpx.Client(base_url=world["paytrust_url"], timeout=15.0) as http:
        while not stop.is_set() and (count is None or sent < count):
            planned = W.next_payment(rng, world)
            for i in range(planned.repeats):
                send_payment(http, world, planned, users, attempt=i)
                sent += 1
                if i < planned.repeats - 1:
                    stop.wait(rng.uniform(1.5, 4.0))
            stop.wait(rng.uniform(*rate))


def reviewer(world: dict, review_after: float, stop: threading.Event) -> None:
    """Priya works the approvals inbox, leaving fresh items for the presenter for a while."""
    op = world["operators"]["reviewer"]
    with httpx.Client(base_url=world["paytrust_url"], timeout=15.0) as http:
        token = None
        while not stop.is_set():
            try:
                if token is None:
                    r = http.post("/v1/auth/login", json={"email": op["email"], "password": op["password"]})
                    r.raise_for_status()
                    token = r.json()["access_token"]
                auth = {"Authorization": f"Bearer {token}"}
                r = http.get("/v1/payments", params={"status": "PENDING_APPROVAL", "limit": 50}, headers=auth)
                if r.status_code == 401:
                    token = None
                    continue
                now = datetime.now(UTC)
                for item in r.json()["items"]:
                    age = (now - datetime.fromisoformat(item["created_at"])).total_seconds()
                    if age < review_after:
                        continue
                    full = http.get(f"/v1/payments/{item['request_id']}", headers=auth).json()
                    factors = {f["name"] for f in full["risk_result"]["factors"]}
                    suspicious = factors & {"merchant_name_mismatch", "duplicate_payment", "category_mismatch"}
                    approve = not suspicious and full["risk_level"] in ("LOW", "MEDIUM")
                    note = ("Called the user, they confirmed the purchase" if approve
                            else "Looks like the agent misbehaved: " + ", ".join(sorted(suspicious or {"high risk"})))
                    action = "approve" if approve else "reject"
                    res = http.post(f"/v1/payments/{item['request_id']}/{action}", json={"note": note}, headers=auth)
                    if res.status_code == 200:
                        colour = C.GREEN if approve else C.RED
                        say(f"{stamp()} {colour}{C.BOLD}{'APPROVED' if approve else 'REJECTED'}{C.RESET} "
                            f"{inr(item['amount']):>10}  by {op['name']} · {C.DIM}{note}{C.RESET}")
                    elif res.status_code == 409:
                        msg = res.json().get("error", {}).get("message", "")
                        say(f"{stamp()} {C.YELLOW}approval refused{C.RESET} {item['request_id']}: {C.DIM}{msg[:140]}{C.RESET}")
            except httpx.HTTPError:
                token = None
            stop.wait(8.0)


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-gap", type=float, default=4.0, help="seconds between payments, lower bound")
    ap.add_argument("--max-gap", type=float, default=9.0, help="seconds between payments, upper bound")
    ap.add_argument("--count", type=int, default=None, help="stop after this many payments")
    ap.add_argument("--review-after", type=float, default=90.0,
                    help="auto-review approvals older than this many seconds (presenter gets them first)")
    ap.add_argument("--no-review", action="store_true", help="leave every approval to the presenter")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    world = load_world()
    stop = threading.Event()
    say(f"{C.BOLD}Live traffic{C.RESET}: {len(world['agents'])} agents shopping for {len(world['users'])} users, "
        f"a payment every {args.min_gap:g}–{args.max_gap:g} s"
        + ("" if args.no_review else f"; Priya reviews approvals older than {args.review_after:g} s") + ".")
    if not args.no_review:
        threading.Thread(target=reviewer, args=(world, args.review_after, stop), daemon=True).start()
    try:
        traffic(world, (args.min_gap, args.max_gap), args.count, args.seed, stop)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
