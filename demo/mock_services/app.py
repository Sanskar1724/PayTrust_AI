"""DemoPay + Agent inbox: the outside world PayTrust talks to in the demo.

DemoPay (a stand-in payment gateway, Razorpay-style)
  Watches PayTrust's live feed as a read-only operator. When a payment is ALLOWED or
  APPROVED, PayTrust attaches an order; DemoPay "shows the customer a checkout", the
  customer pays (or the payment fails), and DemoPay sends a signed Razorpay-format webhook
  (payment.captured / payment.failed / refund.processed) to PayTrust's webhook endpoint.

Agent inbox (stand-in for the AI agents' own servers)
  Receives PayTrust's signed callbacks when a pending payment is approved, rejected or
  expires, and verifies each X-PayTrust-Signature with that agent's webhook secret.

    python -m uvicorn app:app --app-dir demo/mock_services --port 9000   # run_demo.py does this
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import WEBHOOK_SECRET, load_world  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MAX_ROWS = 300
CAPTURE_RATE = 0.94     # share of checkouts the customer completes
REFUND_RATE = 0.04      # share of captured payments refunded a little later
METHODS = ["upi", "upi", "upi", "card", "netbanking"]

world = load_world()
PAYTRUST = world["paytrust_url"]
GATEWAY = world["operators"]["gateway"]
AGENT_BY_SLUG = {a["slug"]: (name, a) for name, a in world["agents"].items()}
AGENT_BY_ID = {a["id"]: name for name, a in world["agents"].items()}
USER_BY_ID = {u["id"]: u for u in world["users"]}

_lock = threading.Lock()
orders: dict[str, dict[str, Any]] = {}          # order_id → order
order_by_request: dict[str, str] = {}
inbox: deque[dict[str, Any]] = deque(maxlen=MAX_ROWS)
gateway_state = {"connected": False, "last_event_at": None, "events_seen": 0, "error": None}
rng = random.Random()


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── PayTrust client (read-only operator) ──

class PayTrustClient:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=PAYTRUST, timeout=10.0)
        self.token: str | None = None

    def login(self) -> None:
        resp = self.http.post("/v1/auth/login", json={"email": GATEWAY["email"], "password": GATEWAY["password"]})
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    def get(self, path: str, **kw) -> httpx.Response:
        if self.token is None:
            self.login()
        resp = self.http.get(path, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        if resp.status_code == 401:
            self.login()
            resp = self.http.get(path, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        return resp

    def ticket(self) -> str:
        if self.token is None:
            self.login()
        resp = self.http.post("/v1/stream/ticket", headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code == 401:
            self.login()
            resp = self.http.post("/v1/stream/ticket", headers={"Authorization": f"Bearer {self.token}"})
        resp.raise_for_status()
        return resp.json()["ticket"]


client = PayTrustClient()


# ── DemoPay: checkout + webhooks ──

def _send_webhook(order: dict[str, Any], event: str, entity_kind: str, entity: dict[str, Any]) -> None:
    body = {
        "entity": "event",
        "account_id": "acc_DemoPayLocal",
        "event": event,
        "contains": [entity_kind],
        "payload": {entity_kind: {"entity": entity}},
        "created_at": int(time.time()),
    }
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    record = {"event": event, "at": _now()}
    try:
        resp = httpx.post(f"{PAYTRUST}/v1/webhooks/razorpay", content=raw, timeout=10.0,
                          headers={"Content-Type": "application/json", "X-Razorpay-Signature": signature})
        record["http_status"] = resp.status_code
        record["result"] = (resp.json() or {}).get("status") if resp.headers.get("content-type", "").startswith(
            "application/json") else None
    except httpx.HTTPError as exc:
        record["http_status"], record["result"] = None, f"error: {exc}"
    with _lock:
        order["webhooks"].append(record)


def _payment_entity(order: dict[str, Any], status: str) -> dict[str, Any]:
    method = order["method"]
    entity = {
        "id": order["payment_id"], "entity": "payment", "amount": order["amount_paise"], "currency": "INR",
        "status": status, "order_id": order["order_id"], "method": method, "captured": status == "captured",
        "email": order["customer_email"], "notes": {"paytrust_request_id": order["request_id"]},
        "created_at": int(time.time()),
    }
    if method == "upi":
        entity["vpa"] = order["customer_email"].split("@")[0] + "@okdemo"
    elif method == "card":
        entity["card"] = {"network": rng.choice(["Visa", "Mastercard", "RuPay"]), "last4": f"{rng.randint(0, 9999):04d}"}
    else:
        entity["bank"] = rng.choice(["HDFC", "ICIC", "SBIN", "UTIB"])
    if status == "failed":
        entity["error_code"], entity["error_description"] = "BAD_REQUEST_ERROR", order["failure_reason"]
    return entity


def _checkout(order_id: str) -> None:
    """The customer reaches DemoPay's checkout and pays (or doesn't)."""
    with _lock:
        order = orders[order_id]
        order["status"] = "attempted"
    time.sleep(rng.uniform(1.0, 3.0))
    if rng.random() < CAPTURE_RATE:
        with _lock:
            order["status"], order["paid_at"] = "captured", _now()
        _send_webhook(order, "payment.captured", "payment", _payment_entity(order, "captured"))
        if rng.random() < REFUND_RATE:
            time.sleep(rng.uniform(15, 40))
            refund = {"id": "rfnd_" + order["payment_id"][4:], "entity": "refund", "amount": order["amount_paise"],
                      "currency": "INR", "payment_id": order["payment_id"], "status": "processed",
                      "notes": {"reason": "Customer returned the item"}}
            with _lock:
                order["status"] = "refunded"
            _send_webhook(order, "refund.processed", "refund", refund)
    else:
        with _lock:
            order["status"] = "failed"
            order["failure_reason"] = rng.choice(["UPI PIN entered incorrectly", "Bank server timeout",
                                                  "Card declined by issuer"])
        _send_webhook(order, "payment.failed", "payment", _payment_entity(order, "failed"))


def _collect(summary: dict[str, Any]) -> None:
    """PayTrust approved money movement: fetch the order it attached and open a checkout."""
    rid = summary["request_id"]
    payment = None
    for _ in range(20):  # the order is attached off the request path, moments after the decision
        resp = client.get(f"/v1/payments/{rid}")
        if resp.status_code == 200 and resp.json().get("order"):
            payment = resp.json()
            break
        time.sleep(0.5)
    if payment is None or (payment["order"] or {}).get("status") == "error":
        return
    order_id = payment["order"]["id"]
    user = USER_BY_ID.get(payment["user_id"], {"name": f"User {payment['user_id']}",
                                                "email": f"user{payment['user_id']}@example.com"})
    with _lock:
        if order_id in orders:
            return
        orders[order_id] = {
            "order_id": order_id, "payment_id": "pay_" + hashlib.sha1(order_id.encode()).hexdigest()[:14],
            "request_id": rid, "amount": payment["amount"], "amount_paise": payment["order"].get("amount")
            or payment["amount"] * 100, "merchant": payment["merchant_name"], "description": payment["description"],
            "agent": AGENT_BY_ID.get(payment["agent_id"], f"Agent {payment['agent_id']}"),
            "customer": user["name"], "customer_email": user["email"], "method": rng.choice(METHODS),
            "paytrust_status": payment["status"], "status": "created", "created_at": _now(), "paid_at": None,
            "webhooks": [],
        }
        order_by_request[rid] = order_id
        if len(orders) > MAX_ROWS:
            oldest = sorted(orders.values(), key=lambda o: o["created_at"])[: len(orders) - MAX_ROWS]
            for o in oldest:
                orders.pop(o["order_id"], None)
                order_by_request.pop(o["request_id"], None)
    time.sleep(rng.uniform(1.0, 4.0))  # the customer opens the checkout page
    _checkout(order_id)


def _watch_paytrust(stop: threading.Event) -> None:
    """Follow PayTrust's live feed (Server-Sent Events) and collect every approved payment."""
    backoff = 1.0
    while not stop.is_set():
        try:
            ticket = client.ticket()
            with httpx.stream("GET", f"{PAYTRUST}/v1/stream", params={"ticket": ticket},
                              timeout=httpx.Timeout(10.0, read=40.0)) as resp:
                resp.raise_for_status()
                gateway_state.update(connected=True, error=None)
                backoff = 1.0
                event = None
                for line in resp.iter_lines():
                    if stop.is_set():
                        return
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event in ("payment.created", "payment.updated"):
                        data = json.loads(line[5:])
                        gateway_state["events_seen"] += 1
                        gateway_state["last_event_at"] = _now()
                        if data.get("status") in ("ALLOWED", "APPROVED") and data.get("source") != "arena":
                            with _lock:
                                known = data["request_id"] in order_by_request
                            if not known:
                                threading.Thread(target=_collect, args=(data,), daemon=True).start()
                    elif not line:
                        event = None
        except Exception as exc:  # PayTrust restarting, network blip: reconnect with a new ticket
            gateway_state.update(connected=False, error=str(exc)[:160])
        stop.wait(backoff)
        backoff = min(backoff * 2, 15.0)


# ── App ──

_stop = threading.Event()


@asynccontextmanager
async def lifespan(_: FastAPI):
    watcher = threading.Thread(target=_watch_paytrust, args=(_stop,), name="demopay-watcher", daemon=True)
    watcher.start()
    yield
    _stop.set()


app = FastAPI(title="DemoPay + Agent inbox (PayTrust demo)", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "gateway_connected": gateway_state["connected"]}


@app.post("/agent-inbox/{slug}")
async def agent_inbox(slug: str, request: Request):
    raw = await request.body()
    name, agent = AGENT_BY_SLUG.get(slug, (slug, None))
    signature = request.headers.get("X-PayTrust-Signature", "")
    verified = bool(agent) and hmac.compare_digest(
        hmac.new(agent["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest(), signature)
    try:
        body = json.loads(raw)
    except ValueError:
        body = {"raw": raw.decode("utf-8", "replace")[:500]}
    inbox.appendleft({"agent": name, "received_at": _now(), "verified": verified, "signature": signature[:16] + "…",
                      "request_id": body.get("request_id"), "status": body.get("status"), "body": body})
    # A real agent would now tell its user what happened, or retry with a different item.
    return {"ok": True, "verified": verified}


@app.get("/api/state")
def state():
    with _lock:
        rows = sorted(orders.values(), key=lambda o: o["created_at"], reverse=True)[:100]
        stats = {s: sum(1 for o in orders.values() if o["status"] == s)
                 for s in ("created", "attempted", "captured", "failed", "refunded")}
        collected = sum(o["amount"] for o in orders.values() if o["status"] == "captured")
    return {"gateway": gateway_state, "orders": rows, "order_stats": stats, "collected": collected,
            "inbox": list(inbox)[:100], "paytrust_url": PAYTRUST}


@app.get("/api/orders/by-request/{request_id}")
def order_for_request(request_id: str):
    with _lock:
        oid = order_by_request.get(request_id)
        return orders.get(oid) if oid else None


@app.get("/api/inbox/by-request/{request_id}")
def inbox_for_request(request_id: str):
    return [m for m in list(inbox) if m["request_id"] == request_id]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
