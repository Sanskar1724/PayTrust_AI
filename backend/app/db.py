"""Database engine + session management.

PostgreSQL in production, SQLite for zero-setup local runs. Both give the evaluation
pipeline the same guarantee — concurrent payments for one user are serialized:
  * PostgreSQL: `SELECT ... FOR UPDATE` on the payer's row (see services/evaluation.py)
  * SQLite: every transaction starts with `BEGIN IMMEDIATE` (one writer at a time)
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def build_engine(url: str) -> Engine:
    settings = get_settings()
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _sqlite_connect(dbapi_conn, _record):
            dbapi_conn.isolation_level = None  # let us emit BEGIN ourselves
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        @event.listens_for(eng, "begin")
        def _sqlite_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        return eng
    return create_engine(
        url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    """(Re)initialise the global engine. Tests call this with an isolated database URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    target = url or get_settings().DATABASE_URL
    if target.startswith("sqlite:///"):
        from pathlib import Path

        Path(target.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    _engine = build_engine(target)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def _session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work: commits on success, rolls back on any exception."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def create_all() -> None:
    """Create tables directly (tests / SQLite dev). Production uses Alembic migrations."""
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(get_engine())
