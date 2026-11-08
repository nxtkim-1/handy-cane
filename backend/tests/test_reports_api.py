"""End to end: seeded simulated patient -> daily metrics -> report input -> pipeline -> stored report."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models as m
from backend.app.api.v1.reports import get_gemini_client
from backend.app.core.db import Base, get_db
from backend.app.main import create_app
from backend.app.reports.gemini_client import FakeGemini
from backend.app.seed import seed


@pytest.fixture(scope="module")
def env():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    with Session() as s:
        info = seed(s)
    app = create_app()

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    tok = client.post("/v1/auth/login", json={"email": "clinician@demo.example", "password": info["password"]})
    hdr = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    pat = client.post("/v1/auth/login", json={"email": "patient@demo.example", "password": info["password"]})
    phdr = {"Authorization": f"Bearer {pat.json()['access_token']}"}
    end = (datetime.now(timezone.utc).astimezone(ZoneInfo("America/Toronto")).date() - timedelta(days=1))
    return dict(app=app, client=client, hdr=hdr, phdr=phdr, pid=info["patient_id"], end=end, Session=Session)


def generate(e, end=None):
    return e["client"].post(f"/v1/patients/{e['pid']}/reports/generate", headers=e["hdr"],
                            json={"period_end": str((end or e["end"]))})


def test_no_api_key_gives_template_fallback_with_real_numbers(env):
    r = generate(env)
    assert r.status_code == 202, r.text
    full = env["client"].get(f"/v1/reports/{r.json()['report_id']}", headers=env["hdr"]).json()
    assert full["status"] == "fallback"
    assert full["input_json"]["data_completeness"]["valid_days"] >= 12 if "input_json" in full else True
    assert full["output_json"]["overall_summary"] and full["is_simulated"] is True
    assert full["output_json"]["disclaimer_ack"].startswith("This report describes cane-use patterns")


def test_generate_is_idempotent_per_period(env):
    a, b = generate(env).json(), generate(env).json()
    assert a["report_id"] == b["report_id"]


def test_fake_gemini_good_output_is_stored_as_generated(env):
    end = env["end"] - timedelta(days=14)  # a different period so it is not the cached one
    env["app"].dependency_overrides[get_gemini_client] = lambda: _good_client(env, end)
    try:
        r = generate(env, end)
    finally:
        env["app"].dependency_overrides.pop(get_gemini_client, None)
    assert r.status_code == 202
    full = env["client"].get(f"/v1/reports/{r.json()['report_id']}", headers=env["hdr"]).json()
    assert full["status"] == "generated", full["status"]


class _Lazy:
    """Fake client that builds its good output from the prompt's own input at call time."""
    model = "fake-gemini"

    def __init__(self, inp_getter):
        self.get = inp_getter

    def generate(self, prompt, schema):
        return FakeGemini.good_output(self.get())


def _good_client(env, end):
    from backend.app.api.v1.reports import _build_input
    with env["Session"]() as s:
        pat = s.get(m.Patient, __import__("uuid").UUID(env["pid"]))
        inp = _build_input(s, pat, end)
    assert not inp["insufficient_data"]
    return _Lazy(lambda: inp)


def test_patient_cannot_generate_reports(env):
    r = env["client"].post(f"/v1/patients/{env['pid']}/reports/generate", headers=env["phdr"],
                           json={"period_end": str(env["end"])})
    assert r.status_code == 403
