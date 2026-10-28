"""Operational commands.

    python -m app.cli init                     # migrate the database + create the first admin
    python -m app.cli create-operator EMAIL NAME ROLE   (password read from PAYTRUST_PASSWORD)
"""
from __future__ import annotations

import argparse
import os
import sys

from app import db
from app.config import get_settings
from app.log import configure_logging, get_logger

logger = get_logger("cli")


def init() -> None:
    from app.main import run_migrations
    from app.services import seed

    db.init_engine()
    run_migrations()
    with db.session_scope() as session:
        seed.bootstrap(session)
    logger.info("Database migrated and bootstrapped")


def create_operator(email: str, name: str, role: str) -> None:
    from app.models import Operator, Role
    from app.services.security import hash_password

    password = os.environ.get("PAYTRUST_PASSWORD", "")
    if len(password) < 8:
        sys.exit("Set PAYTRUST_PASSWORD (at least 8 characters)")
    if role not in Role.ALL:
        sys.exit(f"role must be one of {Role.ALL}")
    db.init_engine()
    with db.session_scope() as session:
        session.add(Operator(email=email.lower(), name=name, role=role, password_hash=hash_password(password)))
    logger.info(f"Created {role} {email}")


def main() -> None:
    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.LOG_JSON)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Run migrations and create the bootstrap admin")
    op = sub.add_parser("create-operator", help="Add a dashboard user")
    op.add_argument("email")
    op.add_argument("name")
    op.add_argument("role", choices=["admin", "reviewer", "viewer"])
    args = parser.parse_args()
    if args.command == "init":
        init()
    else:
        create_operator(args.email, args.name, args.role)


if __name__ == "__main__":
    main()
