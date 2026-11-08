"""Shared test setup. TEST_DATABASE_URL (optional) runs the whole suite against PostgreSQL/TimescaleDB;
the default is a fresh in-memory SQLite database per fixture."""
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.core.db import Base


def make_test_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = create_engine(url)
        Base.metadata.drop_all(eng)
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(autouse=True)
def _isolate_globals():
    from backend.app import escalation, ratelimit
    ratelimit.reset_all()
    escalation.set_sender(None)
    yield
    escalation.set_sender(None)
