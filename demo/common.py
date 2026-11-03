"""Shared paths, settings and helpers for the PayTrust demo environment.

Everything the demo needs lives in this folder. The main project is only *run*, never
modified: PayTrust is started from ../backend with environment variables pointing at the
demo database in demo/.data/.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent
REPO_DIR = DEMO_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
FRONTEND_DIR = REPO_DIR / "frontend"
DATA_DIR = DEMO_DIR / ".data"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "paytrust-demo.db"
WORLD_PATH = DATA_DIR / "world.json"

PAYTRUST_PORT = int(os.environ.get("DEMO_PAYTRUST_PORT", "8000"))
MOCK_PORT = int(os.environ.get("DEMO_MOCK_PORT", "9000"))
PAYTRUST_URL = f"http://127.0.0.1:{PAYTRUST_PORT}"
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}"

# Demo-only credentials. They exist only in the throwaway demo database.
ADMIN_EMAIL = "admin@paytrust.local"
ADMIN_PASSWORD = "demo-admin-2026"
WEBHOOK_SECRET = "whsec_demopay_local_only"


def paytrust_env() -> dict[str, str]:
    """Environment for the PayTrust server (and for in-process setup) in demo mode.

    Every value here is an ordinary PayTrust setting; nothing in the product is patched."""
    env = dict(os.environ)
    env.update({
        "ENVIRONMENT": "development",
        "DATABASE_URL": f"sqlite:///{DB_PATH.as_posix()}",
        "SEED_DEMO_DATA": "false",            # the demo builds its own, larger world
        "AUTO_MIGRATE": "true",
        "ADMIN_EMAIL": ADMIN_EMAIL,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
        "SECRET_KEY": "demo-only-secret-key-not-for-production-0123456789",
        "RAZORPAY_MODE": "simulated",         # orders are created locally; DemoPay plays the gateway
        "RAZORPAY_WEBHOOK_SECRET": WEBHOOK_SECRET,
        # Agent callbacks go to the demo's agent inbox on localhost. This switch exists for local
        # development; production refuses to start with it on.
        "CALLBACK_ALLOW_PRIVATE_NETWORKS": "true",
        "ARENA_BASE_URL": PAYTRUST_URL,
        "CORS_ALLOW_ORIGINS": f"{PAYTRUST_URL},http://localhost:{PAYTRUST_PORT}",
        "RATE_LIMIT_REQUESTS": "600",
        "LOG_LEVEL": "INFO",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def load_world() -> dict[str, Any]:
    if not WORLD_PATH.exists():
        sys.exit("The demo world does not exist yet. Start the demo with:  python demo/run_demo.py")
    return json.loads(WORLD_PATH.read_text(encoding="utf-8"))


def utf8_console() -> None:
    """Make ₹ and box characters print on Windows consoles and through pipes."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")  # enables ANSI colours in the Windows console


def inr(amount: int | float) -> str:
    """Indian digit grouping: 125000 → ₹1,25,000."""
    n = int(round(amount))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if n < 0 else "") + "₹" + s


class C:
    """ANSI colours (no-ops when NO_COLOR is set)."""
    _on = not os.environ.get("NO_COLOR")
    RESET = "\033[0m" if _on else ""
    BOLD = "\033[1m" if _on else ""
    DIM = "\033[2m" if _on else ""
    RED = "\033[31m" if _on else ""
    GREEN = "\033[32m" if _on else ""
    YELLOW = "\033[33m" if _on else ""
    BLUE = "\033[34m" if _on else ""
    MAGENTA = "\033[35m" if _on else ""
    CYAN = "\033[36m" if _on else ""


DECISION_COLOUR = {"ALLOW": C.GREEN, "ASK_USER": C.YELLOW, "DENY": C.RED}


def decision_label(decision: str | None) -> str:
    d = decision or "ERROR"
    return f"{DECISION_COLOUR.get(d, C.MAGENTA)}{C.BOLD}{d:<8}{C.RESET}"


def wait_for(url: str, timeout: float = 60.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False
