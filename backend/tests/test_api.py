from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models as m
from backend.app.core.db import Base, get_db
from backend.app.core.security import hash_secret
from backend.app.main import create_app

PW = "test-password-123"
BOOT = str(uuid.uuid4())
DEV = "cane-test1"


@pytest.fixture()
def env():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    app = create_app()

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)

    with Session() as s:
        def user(name, role):
            u = m.User(email=f"{name}@t.example", display_name=name, role=role, password_hash=hash_secret(PW))
            s.add(u)
            s.flush()
            return u
        doc_a, doc_b, pat_u, cg = user("doca", "clinician"), user("docb", "clinician"), user("pat", "patient"), \
            user("cg", "caregiver")
        patient = m.Patient(user_id=pat_u.user_id, display_name="P", timezone="America/Toronto", is_simulated=True,
                            consent_at=datetime.now(timezone.utc))
        s.add(patient)
        s.flush()
        for u, rel, dis in ((pat_u, "self", True), (cg, "caregiver", False), (doc_a, "clinician", True)):
            s.add(m.CareTeam(patient_id=patient.patient_id, user_id=u.user_id, relation=rel, can_dismiss_events=dis))
        s.add(m.Device(device_id=DEV, secret_hash=hash_secret("code"), is_simulated=True))
        s.flush()
        s.add(m.DeviceAssignment(device_id=DEV, patient_id=patient.patient_id,
                                 valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
        s.commit()
        pid = str(patient.patient_id)

    def login(name) -> dict:
        r = client.post("/v1/auth/login", json={"email": f"{name}@t.example", "password": PW})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    class E:
        pass
    e = E()
    e.client, e.Session, e.pid, e.login = client, Session, pid, login
    e.pat, e.cg, e.doca, e.docb = login("pat"), login("cg"), login("doca"), login("docb")
    return e


def minute(seq, ts, **kw):
    r = dict(type="minute", seq=seq, boot_id=BOOT, ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"), time_quality="synced",
             n_samples=2990, mag_mean=1.0, mag_std=0.05, mag_max=1.5, dyn_mean=0.02, active_s=40, strike_count=30,
             strike_iv_mean=1.1, strike_iv_cv=0.12, upright_s=58, flat_s=0, max_impact_g=1.5)
    r.update(kw)
    return r


def event(seq, ts, eid=None, **kw):
    r = dict(type="event", seq=seq, event_id=str(eid or uuid.uuid4()), boot_id=BOOT,
             ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"), time_quality="corrected", kind="potential_fall",
             outcome="cancelled_by_user", confidence=0.62, peak_g=4.1, tilt_deg=84, still_s=11.5,
             raw_snippet_b64=None)
    r.update(kw)
    return r


def post(e, records, batch_id=None, headers=None, device=DEV):
    return e.client.post("/v1/ingest/batches", headers=headers or e.cg,
                         json={"batch_id": str(batch_id or uuid.uuid4()), "device_id": device, "records": records})


def count(e, model):
    with e.Session() as s:
        return s.scalar(select(func.count()).select_from(model))


T0 = datetime(2026, 3, 2, 13, 0, tzinfo=timezone.utc)  # 08:00 America/Toronto (EST)


def full_day(day_offset, first_seq):
    """720 covered minutes 08:00-20:00 local."""
    start = T0 + timedelta(days=day_offset)
    return [minute(first_seq + i, start + timedelta(minutes=i)) for i in range(720)]


# ------------------------------------------------------------------ ingest

def test_ingest_inserts_then_dedups_on_device_seq(env):
    recs = [minute(1, T0), event(2, T0 + timedelta(seconds=47))]
    r = post(env, recs)
    assert r.status_code == 200
    body = r.json()
    assert (body["received"], body["inserted"], body["duplicates"], body["rejected"]) == (2, 2, 0, [])
    assert body["server_max_seq"] == 2

    # Same records in a NEW batch (e.g. second phone): nothing is double counted.
    r2 = post(env, recs)
    assert r2.json()["inserted"] == 0 and r2.json()["duplicates"] == 2
    assert count(env, m.MinuteMetric) == 1 and count(env, m.DeviceEvent) == 1

    # Duplicate within a single batch, and a mix of new + old
    r3 = post(env, [minute(3, T0 + timedelta(minutes=1)), minute(3, T0 + timedelta(minutes=2)), recs[0]])
    assert (r3.json()["inserted"], r3.json()["duplicates"]) == (1, 2)
    assert count(env, m.MinuteMetric) == 2


def test_batch_replay_returns_same_response_and_no_rows(env):
    bid = uuid.uuid4()
    r1 = post(env, [minute(1, T0), minute(2, T0 + timedelta(minutes=1))], batch_id=bid)
    n = count(env, m.MinuteMetric)
    # replay, even with different content under the same batch_id: stored response, no new rows
    r2 = post(env, [minute(1, T0), minute(9, T0 + timedelta(minutes=9))], batch_id=bid)
    assert r2.status_code == 200 and r2.json() == r1.json()
    assert count(env, m.MinuteMetric) == n == 2
    assert count(env, m.IngestBatch) == 1


def test_rejected_records_listed_rest_accepted(env):
    recs = [minute(1, T0),
            minute(2, T0 + timedelta(minutes=1), n_samples=9999),
            minute(3, T0 + timedelta(minutes=2), active_s=61),
            {"type": "bogus", "seq": 4},
            event(5, T0, kind="exploded"),
            minute(6, T0 + timedelta(minutes=5), time_quality="maybe"),
            minute(7, T0 + timedelta(minutes=6))]
    body = post(env, recs).json()
    assert body["inserted"] == 2 and body["duplicates"] == 0
    assert [x["index"] for x in body["rejected"]] == [1, 2, 3, 4, 5]
    assert all(x["reason"] for x in body["rejected"])
    assert body["rejected"][0]["seq"] == 2
    assert count(env, m.MinuteMetric) == 2


def test_ingest_requires_consent_pairing_and_care_team(env):
    with env.Session() as s:
        p = s.get(m.Patient, uuid.UUID(env.pid))
        p.consent_at = None
        s.commit()
    r = post(env, [minute(1, T0)])
    assert r.status_code == 403 and r.json()["error"]["code"] == "consent_required"
    assert count(env, m.MinuteMetric) == 0
    # unknown device
    assert post(env, [minute(1, T0)], device="cane-nope").status_code == 403
    # clinician (not a paired app user) and unrelated clinician cannot upload
    assert post(env, [minute(1, T0)], headers=env.docb).status_code == 403
    assert post(env, [minute(1, T0)], headers=env.doca).status_code == 403
    # no token
    assert env.client.post("/v1/ingest/batches", json={}).status_code == 401


def test_ingest_batch_size_limit(env):
    recs = [minute(i, T0 + timedelta(minutes=i)) for i in range(2001)]
    assert post(env, recs).status_code == 413


def test_simulated_flag_carried_through(env):
    post(env, [event(1, T0), minute(2, T0)])
    ev = env.client.get(f"/v1/patients/{env.pid}/events", headers=env.doca).json()
    assert ev[0]["is_simulated"] is True
    assert env.client.get("/v1/me", headers=env.doca).json()["patients"][0]["is_simulated"] is True
    ov = env.client.get(f"/v1/patients/{env.pid}/overview", headers=env.doca).json()
    assert ov["patient"]["is_simulated"] is True and ov["device"]["is_simulated"] is True


# ------------------------------------------------------------------ access control

def test_clinician_cannot_read_other_clinicians_patient(env):
    for path in ("overview", "daily", "baseline", "events", "reports"):
        r = env.client.get(f"/v1/patients/{env.pid}/{path}", headers=env.docb)
        assert r.status_code == 403, path
        assert r.json()["error"]["code"] == "forbidden"
        assert env.client.get(f"/v1/patients/{env.pid}/{path}", headers=env.doca).status_code == 200, path
    assert env.client.get("/v1/patients", headers=env.docb).json() == []
    assert len(env.client.get("/v1/patients", headers=env.doca).json()) == 1
    assert env.client.post(f"/v1/patients/{env.pid}/baseline", headers=env.docb,
                           json={"start_day": "2026-03-01", "end_day": "2026-03-14"}).status_code == 403


def test_revoked_membership_loses_access(env):
    with env.Session() as s:
        ct = s.get(m.CareTeam, (uuid.UUID(env.pid), s.scalars(select(m.User.user_id).where(
            m.User.email == "doca@t.example")).one()))
        ct.revoked_at = datetime.now(timezone.utc)
        s.commit()
    assert env.client.get(f"/v1/patients/{env.pid}/overview", headers=env.doca).status_code == 403


def test_auth_login_refresh_rotation(env):
    r = env.client.post("/v1/auth/login", json={"email": "DocA@t.example", "password": PW})
    assert r.status_code == 200
    rt = r.json()["refresh_token"]
    r2 = env.client.post("/v1/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code == 200 and r2.json()["refresh_token"] != rt
    # rotated token cannot be reused
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": rt}).status_code == 401
    # access token is not a refresh token
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": r.json()["access_token"]}).status_code == 401
    assert env.client.post("/v1/auth/login", json={"email": "doca@t.example", "password": "wrong"}).status_code == 401
    assert env.client.get("/health").json() == {"status": "ok"}


# ------------------------------------------------------------------ events

def test_dismiss_audited_and_event_kept(env):
    eid = uuid.uuid4()
    post(env, [event(1, T0, eid=eid)])
    url = f"/v1/events/{eid}"
    # unrelated clinician cannot touch it (and learns nothing)
    assert env.client.patch(url, headers=env.docb, json={"status": "acknowledged"}).status_code == 403
    # caregiver may acknowledge but not dismiss
    assert env.client.patch(url, headers=env.cg, json={"status": "dismissed", "reason": "x"}).status_code == 403
    assert env.client.patch(url, headers=env.cg, json={"status": "acknowledged"}).json()["status"] == "acknowledged"
    # dismissal needs a reason
    assert env.client.patch(url, headers=env.doca, json={"status": "dismissed"}).status_code == 422
    r = env.client.patch(url, headers=env.doca, json={"status": "dismissed", "reason": "false_alarm_dropped_cane",
                                                       "note": "dropped it getting into the car"})
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed" and r.json()["status_reason"] == "false_alarm_dropped_cane"
    # never deleted: still listed
    evs = env.client.get(f"/v1/patients/{env.pid}/events?status=dismissed", headers=env.doca).json()
    assert [x["event_id"] for x in evs] == [str(eid)]
    with env.Session() as s:
        logs = list(s.scalars(select(m.AuditLog).where(m.AuditLog.action.in_(["dismiss_event", "acknowledge_event"]))
                              .order_by(m.AuditLog.id)))
        assert [l.action for l in logs] == ["acknowledge_event", "dismiss_event"]
        d = logs[-1]
        assert d.detail["event_id"] == str(eid) and d.detail["from"] == "acknowledged" \
            and d.detail["to"] == "dismissed" and d.detail["reason"] == "false_alarm_dropped_cane"
        assert str(d.patient_id) == env.pid and d.user_id is not None
        assert s.scalar(select(func.count()).select_from(m.DeviceEvent)) == 1
    # dismissed is final
    assert env.client.patch(url, headers=env.doca, json={"status": "acknowledged"}).status_code == 409


# ------------------------------------------------------------------ daily metrics / missing data

def test_missing_days_not_counted_as_zero(env):
    # day 0 valid (12 h), day 1 absent entirely, day 2 only 3 h (invalid), day 3 valid but all minutes unsynced
    recs = full_day(0, 1) + full_day(2, 1000)[:180]
    recs += [minute(5000 + i, T0 + timedelta(days=3, minutes=i), time_quality="unsynced") for i in range(720)]
    for i in range(0, len(recs), 700):
        assert post(env, recs[i:i + 700]).status_code == 200
    r = env.client.get(f"/v1/patients/{env.pid}/daily?from=2026-03-02&to=2026-03-05", headers=env.doca)
    days = {d["day"]: d for d in r.json()}
    assert len(days) == 4

    d0 = days["2026-03-02"]
    assert d0["valid"] is True and d0["coverage_h"] == 12.0
    assert d0["active_min"] == pytest.approx(720 * 40 / 60) and d0["strikes"] == 720 * 30
    assert d0["bouts"] == 1 and d0["bout_longest_s"] == 720 * 60.0

    d1 = days["2026-03-03"]  # no records at all: no data, not zero
    assert d1["no_data"] is True and d1["valid"] is False and d1["active_min"] is None and d1["strikes"] is None

    d2 = days["2026-03-04"]  # partial: coverage reported, metrics withheld
    assert d2["valid"] is False and d2["coverage_h"] == 3.0
    assert d2["active_min"] is None and d2["strikes"] is None and d2["active_by_hour"] is None

    d3 = days["2026-03-05"]  # unsynced rows stored but excluded
    assert d3["valid"] is False and d3["coverage_h"] == 0.0 and d3["active_min"] is None
    assert count(env, m.MinuteMetric) == 720 + 180 + 720

    # analytics series treats these as missing (NaN), not zeros
    from backend.app.metrics.daily import metric_series
    with env.Session() as s:
        first, series = metric_series(s, uuid.UUID(env.pid))
    import numpy as np
    assert first == date(2026, 3, 2)
    assert not np.isnan(series["active_min"][0]) and np.isnan(series["active_min"][1:]).all()


def test_low_sample_minutes_not_covered_and_events_counted():
    from zoneinfo import ZoneInfo
    from backend.app.metrics.daily import compute_day
    tz = ZoneInfo("America/Toronto")
    mins = [dict(ts=T0 + timedelta(minutes=i), n_samples=2000 if i == 100 else 2990, time_quality="synced",
                 active_s=30, strike_count=30, strike_iv_cv=0.1) for i in range(720)]
    out = compute_day(mins, [dict(kind="potential_fall", outcome="cancelled_by_user"),
                             dict(kind="help_request", outcome="escalated")], tz)
    assert out["coverage_h"] == round(719 / 60, 3) and out["valid"] is True
    assert (out["events_potential_fall"], out["events_cancelled"], out["help_presses"]) == (1, 1, 1)
    # the one uncovered minute is a gap of 1 minute, so the bout is merged across it
    assert out["bouts"] == 1


def test_baseline_endpoint_needs_enough_valid_days(env):
    r = env.client.post(f"/v1/patients/{env.pid}/baseline", headers=env.doca,
                        json={"start_day": "2026-03-02", "end_day": "2026-03-15"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_data"
