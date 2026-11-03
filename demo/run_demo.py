"""Start the whole PayTrust demo with one command.

    .venv\\Scripts\\python demo\\run_demo.py            (Windows)
    .venv/bin/python demo/run_demo.py                 (macOS / Linux)

What it does:
  1. Checks Python packages and free ports.
  2. Builds the operator console once (frontend/dist, git-ignored) if it is missing or stale.
  3. Creates a fresh demo world in demo/.data/: team, 4 agents, 15 merchants, 40 users,
     74 policies and 24 hours of history produced by PayTrust's own engines.
  4. Starts PayTrust (API + console) on :8000 and DemoPay + Agent inbox on :9000.
  5. Streams live agent traffic in this window. Ctrl+C stops everything.

Options: --keep (reuse the existing world), --no-traffic, --no-review, --open (open browser tabs).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    BACKEND_DIR,
    DATA_DIR,
    DB_PATH,
    DEMO_DIR,
    FRONTEND_DIR,
    LOG_DIR,
    MOCK_PORT,
    MOCK_URL,
    PAYTRUST_PORT,
    PAYTRUST_URL,
    WORLD_PATH,
    C,
    load_world,
    paytrust_env,
    utf8_console,
    wait_for,
)

REQUIRED = ["fastapi", "uvicorn", "sqlalchemy", "alembic", "httpx", "bcrypt", "jwt", "pydantic_settings"]
children: list[tuple[str, subprocess.Popen]] = []


def fail(msg: str) -> None:
    print(f"\n{C.RED}{C.BOLD}✗ {msg}{C.RESET}")
    stop_all()
    sys.exit(1)


def step(msg: str) -> None:
    print(f"{C.CYAN}›{C.RESET} {msg}", flush=True)


def check_python() -> None:
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        fail(f"Missing Python packages: {', '.join(missing)}.\n  Use the project's virtual environment, e.g.\n"
             f"    .venv\\Scripts\\python demo\\run_demo.py\n  or install them:  pip install -r backend/requirements.txt")


def check_ports() -> None:
    for port in (PAYTRUST_PORT, MOCK_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                fail(f"Port {port} is already in use. Stop whatever runs there (another PayTrust?) "
                     f"or set DEMO_PAYTRUST_PORT / DEMO_MOCK_PORT.")


def ensure_console() -> None:
    dist = FRONTEND_DIR / "dist" / "index.html"
    sources = [p for p in (FRONTEND_DIR / "src").rglob("*") if p.is_file()] + [FRONTEND_DIR / "index.html"]
    newest = max(p.stat().st_mtime for p in sources)
    if dist.exists() and dist.stat().st_mtime >= newest:
        return
    npm = shutil.which("npm")
    if npm is None:
        fail("The operator console needs a one-time build, but Node.js/npm was not found (install Node 20+).")
    step("Building the operator console (one time, about 30 s) …")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=FRONTEND_DIR, check=True)
    result = subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stdout[-2000:], result.stderr[-2000:])
        fail("Console build failed (output above).")


def ensure_world(keep: bool) -> None:
    if keep and DB_PATH.exists() and WORLD_PATH.exists():
        step("Reusing the existing demo world (--keep). History stays as it was.")
        return
    for path in (DB_PATH, WORLD_PATH, DB_PATH.with_suffix(".db-wal"), DB_PATH.with_suffix(".db-shm")):
        path.unlink(missing_ok=True)
    step("Creating the demo world and 24 hours of history …")
    result = subprocess.run([sys.executable, str(DEMO_DIR / "setup_world.py")], env=paytrust_env(),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    (LOG_DIR / "setup.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:])
        fail("Creating the demo world failed (see above, full log in demo/.data/logs/setup.log).")
    for line in result.stdout.splitlines():
        if line.startswith("  "):
            print(f"  {C.DIM}{line.strip()}{C.RESET}")


def start(name: str, args: list[str], cwd: Path, env: dict[str, str], log: str) -> subprocess.Popen:
    out = open(LOG_DIR / log, "w", encoding="utf-8")
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT)
    children.append((name, proc))
    return proc


def stop_all() -> None:
    for _name, proc in reversed(children):
        if proc.poll() is None:
            proc.terminate()
    for _name, proc in children:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    children.clear()


def banner(world: dict) -> None:
    ops = world["operators"]
    line = f"{C.DIM}{'─' * 78}{C.RESET}"
    py = ".venv\\Scripts\\python demo\\story.py" if os.name == "nt" else ".venv/bin/python demo/story.py"
    print(f"""
{line}
{C.BOLD}{C.GREEN}  PayTrust demo is running{C.RESET}
{line}
  {C.BOLD}PayTrust console{C.RESET}   {PAYTRUST_URL}
     admin     {ADMIN_EMAIL:<32} {ADMIN_PASSWORD}
     reviewer  {ops['reviewer']['email']:<32} {ops['reviewer']['password']}
     viewer    {ops['viewer']['email']:<32} {ops['viewer']['password']}
  {C.BOLD}API reference{C.RESET}      {PAYTRUST_URL}/docs
  {C.BOLD}DemoPay + inbox{C.RESET}    {MOCK_URL}
  {C.BOLD}Guided story{C.RESET}       in a second terminal:  {py}
  {C.BOLD}Logs{C.RESET}               demo/.data/logs/
{line}
  Ctrl+C stops everything.
{line}""", flush=True)


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="reuse the existing demo world instead of a fresh one")
    ap.add_argument("--no-traffic", action="store_true", help="don't run live agent traffic")
    ap.add_argument("--no-review", action="store_true", help="leave every approval to the presenter")
    ap.add_argument("--open", action="store_true", help="open the console and DemoPay in the browser")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    check_python()
    check_ports()
    ensure_console()
    ensure_world(args.keep)
    world = load_world()

    step(f"Starting PayTrust on {PAYTRUST_URL} …")
    env = paytrust_env()
    start("PayTrust", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                  "--port", str(PAYTRUST_PORT)], BACKEND_DIR, env, "paytrust.log")
    if not wait_for(f"{PAYTRUST_URL}/ready", 60):
        fail(f"PayTrust did not start. Last log lines:\n{(LOG_DIR / 'paytrust.log').read_text(encoding='utf-8')[-2500:]}")

    step(f"Starting DemoPay + Agent inbox on {MOCK_URL} …")
    start("DemoPay", [sys.executable, "-m", "uvicorn", "app:app", "--app-dir", str(DEMO_DIR / "mock_services"),
                             "--host", "127.0.0.1", "--port", str(MOCK_PORT), "--no-access-log"],
          DEMO_DIR, env, "demopay.log")
    if not wait_for(f"{MOCK_URL}/health", 30):
        fail(f"DemoPay did not start. Last log lines:\n{(LOG_DIR / 'demopay.log').read_text(encoding='utf-8')[-2500:]}")

    banner(world)
    if args.open:
        webbrowser.open(PAYTRUST_URL)
        webbrowser.open(MOCK_URL)

    traffic = None
    if not args.no_traffic:
        cmd = [sys.executable, str(DEMO_DIR / "simulator.py")] + (["--no-review"] if args.no_review else [])
        traffic = subprocess.Popen(cmd, env=env)
        children.append(("traffic", traffic))
    try:
        while True:
            for name, proc in list(children):
                if proc.poll() is not None and proc is not traffic:
                    fail(f"{name} stopped unexpectedly (exit {proc.returncode}). See demo/.data/logs/.")
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{C.DIM}Stopping …{C.RESET}")
    finally:
        stop_all()
        print("Demo stopped. Start it again with --keep to continue with the same data.")


if __name__ == "__main__":
    main()
