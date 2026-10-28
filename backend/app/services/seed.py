"""Startup bootstrap: the first admin account, plus optional demo data for a fresh database."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.log import get_logger
from app.models import Agent, Merchant, Operator, Policy, Role, User
from app.services.security import hash_password, new_webhook_secret

logger = get_logger("seed")

DEMO_MERCHANTS = [
    ("TechMart Electronics", "electronics", "standard"),
    ("BookHaven", "books", "standard"),
    ("TravelEase", "travel", "standard"),
    ("FreshCart", "grocery", "standard"),
    ("BetZone", "gambling", "high"),
    ("QuickLoans Direct", "financial_products", "high"),
]


def bootstrap(session: Session) -> None:
    s = get_settings()
    if not session.scalar(select(func.count()).select_from(Operator)):
        session.add(Operator(email=s.ADMIN_EMAIL.lower(), name="Administrator", role=Role.ADMIN,
                             password_hash=hash_password(s.ADMIN_PASSWORD)))
        logger.info(f"Created bootstrap admin {s.ADMIN_EMAIL}")
    if s.SEED_DEMO_DATA and not session.scalar(select(func.count()).select_from(User)):
        seed_demo(session)


def seed_demo(session: Session) -> None:
    asha = User(name="Asha Verma", email="asha@example.com", external_ref="demo-asha")
    rohan = User(name="Rohan Mehta", email="rohan@example.com", external_ref="demo-rohan")
    shopper = Agent(name="Shopping Assistant", description="Buys electronics and books for the user",
                    webhook_secret=new_webhook_secret())
    planner = Agent(name="Travel Planner", description="Books trips and travel extras",
                    webhook_secret=new_webhook_secret())
    session.add_all([asha, rohan, shopper, planner])
    session.add_all(Merchant(name=n, category=c, risk_tier=t) for n, c, t in DEMO_MERCHANTS)
    session.flush()
    session.add_all([
        Policy(user_id=asha.id, agent_id=shopper.id, daily_limit=100_000, max_transaction=60_000,
               approval_threshold=30_000, allowed_categories=["electronics", "books", "travel"],
               blocked_categories=["gambling", "financial_products"], updated_by="seed"),
        Policy(user_id=rohan.id, agent_id=shopper.id, daily_limit=50_000, max_transaction=25_000,
               approval_threshold=10_000, allowed_categories=["electronics", "books", "grocery"],
               blocked_categories=["gambling", "financial_products"], updated_by="seed"),
        Policy(user_id=rohan.id, agent_id=planner.id, daily_limit=200_000, max_transaction=150_000,
               approval_threshold=50_000, allowed_categories=["travel"],
               blocked_categories=["gambling", "financial_products"], updated_by="seed"),
    ])
    logger.info("Seeded demo users, agents, merchants and policies")
