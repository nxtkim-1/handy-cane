from __future__ import annotations

import logging
from pathlib import Path

from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from backend.app.core.config import settings


class UTCDateTime(TypeDecorator):
    """timestamptz on PostgreSQL; on SQLite stores naive UTC and always returns aware UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use UTC-aware values")
        value = value.astimezone(timezone.utc)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


_TIMESCALE_SQL = Path(__file__).resolve().parents[2] / "migrations" / "002_timescale.sql"


def init_db(eng: Engine | None = None) -> None:
    from backend.app import models  # noqa: F401  (register tables)

    eng = eng or engine
    Base.metadata.create_all(eng)
    if eng.dialect.name == "postgresql":
        # Hypertables + compression (idempotent). Plain PostgreSQL without TimescaleDB: skip, don't crash.
        try:
            with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql(_TIMESCALE_SQL.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("TimescaleDB setup skipped: %s", str(e)[:200])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
