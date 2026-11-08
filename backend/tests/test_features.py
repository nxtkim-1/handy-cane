"""Severity, event extras, escalation, scheduler jobs, consent/privacy, rate limits, report timing."""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.app import escalation, ratelimit
from backend.app import models as m
from backend.app import scheduler
from backend.app.api.v1 import reports as reports_api
from backend.app.core.config import settings, warn_if_weak_secret
from backend.app.severity import severity_for
from backend.tests.test_api import DEV, PW, T0, count, env, event, minute, post  # noqa: F401

NOW = datetime.now(timezone.utc)


def ev_ts(minutes_ago=5):
    return (NOW - timedelta(minutes=minutes_ago)).replace(microsecond=0)


# ------------------------------------------------------------------ severity

@pytest.mark.parametrize("kind,outcome,peak,cause,sev,reason", [
    ("help_request", "escalated", None, None, "high", "The help button was held on the cane."),
    ("help_request", "cancelled_by_user", 0.0, None, "high", "The help button was held on the cane."),
    ("potential_fall", "escalated", 5.0, None, "high", "Nobody cancelled the alarm on the cane."),
    ("potential_fall", "acknowledged_on_cane", 5.0, None, "medium",
     "The alarm sounded and was switched off on the cane."),
    ("potential_fall", "cancelled_by_user", 3.0, None, "medium", "Cancelled on the cane after a hard impact."),
    ("potential_fall", "cancelled_by_user", 2.99, None, "low", "Cancelled on the cane; no hard impact."),
    ("potential_fall", "cancelled_by_user", None, None, "low", "Cancelled on the cane; no hard impact."),
    ("impact_only", "cancelled_by_user", 6.0, None, "low", "A bump was recorded; the cane stayed upright."),
    ("potential_fall", "escalated", None, "cane_down_still", "high", None),
    ("mystery", "escalated", 1.0, None, "medium", "Unrecognised event; please check."),
    ("potential_fall", "weird", 1.0, None, "medium", "Unrecognised event; please check."),
])
def test_severity_table(kind, outcome, peak, cause, sev, reason):
    s, r = severity_for(SimpleNamespace(kind=kind, outcome=outcome, peak_g=peak, cause=cause))
    assert s == sev
    if reason:
        assert r == reason
    else:
        assert "no impact" in r.lower()


# ------------------------------------------------------------------ extras, listing, overview

def test_event_extras_stored_unknown_fields_ignored_long_cause_rejected(env):
    e1 = event(1, ev_ts(30), kind="potential_fall", outcome="escalated", cause="cane_down_still",
               source="cane", firmware_future_field=7)
    bad = event(2, ev_ts(29), cause="x" * 41)
    r = post(env, [e1, bad])
    assert r.status_code == 200 and r.json()["inserted"] == 1 and len(r.json()["rejected"]) == 1
    with env.Session() as s:
        x = s.get(m.EventExtra, uuid.UUID(e1["event_id"]))
        assert (x.cause, x.source) == ("cane_down_still", "cane")
    out = env.client.get(f"/v1/patients/{env.pid}/events", headers=env.cg).json()
    assert out[0]["cause"] == "cane_down_still" and out[0]["severity"] == "high"
    assert "no impact" in out[0]["severity_reason"].lower()


def test_events_sorted_open_first_then_severity_then_newest_and_overview(env):
    recs = [
        event(1, ev_ts(50), kind="impact_only", outcome="cancelled_by_user"),                    # low
        event(2, ev_ts(40), kind="potential_fall", outcome="acknowledged_on_cane"),              # medium
        event(3, ev_ts(30), kind="potential_fall", outcome="escalated"),                         # high, older
        event(4, ev_ts(20), kind="help_request", outcome="escalated", peak_g=0),                 # high, newer
        event(5, ev_ts(10), kind="impact_only", outcome="cancelled_by_user"),                    # low, newer
    ]
    assert post(env, recs).status_code == 200
    out = env.client.get(f"/v1/patients/{env.pid}/events", headers=env.cg).json()
    assert [(o["severity"], o["kind"]) for o in out] == [
        ("high", "help_request"), ("high", "potential_fall"), ("medium", "potential_fall"),
        ("low", "impact_only"), ("low", "impact_only")]
    # acknowledge the newest high event: it moves behind all open ones
    r = env.client.patch(f"/v1/events/{out[0]['event_id']}", headers=env.cg, json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["severity"] == "high"
    out2 = env.client.get(f"/v1/patients/{env.pid}/events", headers=env.cg).json()
    assert out2[-1]["event_id"] == out[0]["event_id"] and out2[-1]["status"] == "acknowledged"
    assert [o["status"] for o in out2] == ["open"] * 4 + ["acknowledged"]

    ov = env.client.get(f"/v1/patients/{env.pid}/overview", headers=env.cg).json()
    assert ov["open_events"] == 4
    assert ov["open_events_by_severity"] == {"high": 1, "medium": 1, "low": 2}

    lst = env.client.get("/v1/patients", headers=env.cg).json()[0]
    assert lst["open_events"] == 4 and lst["open_high_events"] == 1
    assert lst["last_sync_at"] is not None and lst["stale_sync"] is False and lst["sustained_change"] is False


def test_patient_list_stale_and_sustained(env):
    lst = env.client.get("/v1/patients", headers=env.cg).json()[0]
    assert lst["last_sync_at"] is None and lst["stale_sync"] is True
    with env.Session() as s:
        s.get(m.Device, DEV).last_seen_at = NOW - timedelta(hours=47)
        s.add(m.ChangeFlag(patient_id=uuid.UUID(env.pid), metric="active_min", day=date.today(),
                           direction="down", method="cusum", value=1.0))
        s.commit()
    lst = env.client.get("/v1/patients", headers=env.cg).json()[0]
    assert lst["stale_sync"] is False and lst["sustained_change"] is True
    with env.Session() as s:
        s.get(m.Device, DEV).last_seen_at = NOW - timedelta(hours=49)
        s.commit()
    assert env.client.get("/v1/patients", headers=env.cg).json()[0]["stale_sync"] is True


# ------------------------------------------------------------------ escalation

class FakeSender:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, text):
        self.calls.append((url, text))
        if self.fail:
            raise RuntimeError("boom")


@pytest.fixture()
def hook(monkeypatch):
    monkeypatch.setattr(settings, "escalation_webhook_url", "https://hook.example/x")
    monkeypatch.setattr(settings, "escalation_repeat_minutes", 10)
    monkeypatch.setattr(settings, "escalation_max_repeats", 3)
    fake = FakeSender()
    escalation.set_sender(fake)
    return fake


def high_event(seq=1, **kw):
    return event(seq, ev_ts(1), kind="help_request", outcome="escalated", **kw)


def test_escalation_sent_once_then_repeats_then_stops_at_max(env, hook):
    assert post(env, [high_event()]).status_code == 200
    assert len(hook.calls) == 1
    url, text = hook.calls[0]
    assert url == "https://hook.example/x"
    assert "HIGH" in text and "help request" in text and "Open the Smart Cane app to respond." in text
    assert "P:" in text  # patient display name

    # re-ingesting the same event does not notify again
    post(env, [high_event()])
    assert len(hook.calls) == 1

    t = datetime.now(timezone.utc)
    assert escalation.run_repeat_check(env.Session, t + timedelta(minutes=5)) == 0
    assert escalation.run_repeat_check(env.Session, t + timedelta(minutes=11)) == 1
    assert escalation.run_repeat_check(env.Session, t + timedelta(minutes=12)) == 0  # not yet 10 min after #2
    assert escalation.run_repeat_check(env.Session, t + timedelta(minutes=22)) == 1
    assert escalation.run_repeat_check(env.Session, t + timedelta(minutes=60)) == 0  # max 3 total
    assert len(hook.calls) == 3

    rows = env.client.get(f"/v1/patients/{env.pid}/escalations", headers=env.cg).json()
    assert sorted(r["attempt"] for r in rows) == [1, 2, 3]
    assert all(r["ok"] and r["channel"] == "webhook" for r in rows)
    assert set(rows[0]) == {"event_id", "sent_at", "channel", "ok", "attempt"}


def test_acknowledge_stops_repeats(env, hook):
    ev = high_event()
    post(env, [ev])
    r = env.client.patch(f"/v1/events/{ev['event_id']}", headers=env.cg, json={"status": "acknowledged"})
    assert r.status_code == 200
    assert escalation.run_repeat_check(env.Session, datetime.now(timezone.utc) + timedelta(hours=1)) == 0
    assert len(hook.calls) == 1


def test_dismiss_stops_repeats(env, hook):
    ev = high_event()
    post(env, [ev])
    env.client.patch(f"/v1/events/{ev['event_id']}", headers=env.doca,
                     json={"status": "dismissed", "reason": "false alarm"})
    assert escalation.run_repeat_check(env.Session, datetime.now(timezone.utc) + timedelta(hours=1)) == 0


def test_sender_failure_does_not_break_ingest(env, hook):
    hook.fail = True
    r = post(env, [high_event(), minute(2, T0)])
    assert r.status_code == 200 and r.json()["inserted"] == 2
    rows = env.client.get(f"/v1/patients/{env.pid}/escalations", headers=env.cg).json()
    assert len(rows) == 1 and rows[0]["ok"] is False
    with env.Session() as s:
        assert "boom" in s.scalars(select(m.Escalation)).first().error


def test_low_and_medium_events_do_not_escalate(env, hook):
    post(env, [event(1, ev_ts(3), kind="impact_only"),
               event(2, ev_ts(2), kind="potential_fall", outcome="acknowledged_on_cane")])
    assert hook.calls == [] and count(env, m.Escalation) == 0


def test_no_webhook_logs_and_records(env, monkeypatch, caplog):
    monkeypatch.setattr(settings, "escalation_webhook_url", "")
    fake = FakeSender()
    escalation.set_sender(fake)
    with caplog.at_level(logging.WARNING):
        assert post(env, [high_event()]).status_code == 200
    assert fake.calls == []
    assert any("ESCALATION" in r.message for r in caplog.records)
    rows = env.client.get(f"/v1/patients/{env.pid}/escalations", headers=env.cg).json()
    assert len(rows) == 1 and rows[0]["channel"] == "log"


def test_escalations_endpoint_is_care_team_only(env, hook):
    post(env, [high_event()])
    assert env.client.get(f"/v1/patients/{env.pid}/escalations", headers=env.docb).status_code == 403


# ------------------------------------------------------------------ scheduler jobs

def test_job_escalation_check(env, hook):
    post(env, [high_event()])
    assert scheduler.escalation_check_job(env.Session, datetime.now(timezone.utc) + timedelta(minutes=11)) == 1


def test_job_purge_tokens(env):
    n0 = count(env, m.RefreshToken)
    assert n0 >= 4  # logins in the fixture
    with env.Session() as s:
        toks = list(s.scalars(select(m.RefreshToken)))
        toks[0].revoked_at = NOW
        toks[1].expires_at = NOW - timedelta(days=1)
        s.commit()
    assert scheduler.purge_tokens_job(env.Session) == 2
    assert count(env, m.RefreshToken) == n0 - 2


def test_job_daily_reports_runs_only_for_due_period_and_is_idempotent(env):
    pid = uuid.UUID(env.pid)
    now = datetime(2026, 4, 15, 7, 0, tzinfo=timezone.utc)  # 03:00 Toronto, local yesterday = Apr 14
    with env.Session() as s:
        s.get(m.Patient, pid).report_anchor = date(2026, 4, 1)   # period 1 = Apr 1..Apr 14 ended yesterday
        s.commit()
    client = reports_api._NoGemini()
    ids = scheduler.daily_reports_job(env.Session, now, client)
    assert len(ids) == 1
    with env.Session() as s:
        r = s.scalars(select(m.Report)).one()
        assert (r.period_start, r.period_end) == (date(2026, 4, 1), date(2026, 4, 14))
        assert s.scalars(select(m.AuditLog).where(m.AuditLog.action == "generate_report")).first().user_id is None
    assert scheduler.daily_reports_job(env.Session, now, client) == ids  # same report, no duplicate
    assert count(env, m.Report) == 1
    # a day later no period has just ended
    assert scheduler.daily_reports_job(env.Session, now + timedelta(days=1), client) == []
    # anchor in the future: nothing
    with env.Session() as s:
        s.get(m.Patient, pid).report_anchor = date(2026, 5, 1)
        s.commit()
    assert scheduler.daily_reports_job(env.Session, now, client) == []


def test_job_daily_reports_uses_endpoint_client_selection(env, monkeypatch):
    seen = []
    monkeypatch.setattr(reports_api, "get_gemini_client", lambda: seen.append(1) or reports_api._NoGemini())
    with env.Session() as s:
        s.get(m.Patient, uuid.UUID(env.pid)).report_anchor = date(2026, 4, 1)
        s.commit()
    scheduler.daily_reports_job(env.Session, datetime(2026, 4, 15, 7, 0, tzinfo=timezone.utc))
    assert seen == [1]


# ------------------------------------------------------------------ consent and privacy

def test_consent_withdraw_blocks_ingest_and_is_self_only(env):
    assert post(env, [minute(1, T0)]).status_code == 200
    assert env.client.post(f"/v1/patients/{env.pid}/consent/withdraw", headers=env.cg).status_code == 403
    r = env.client.post(f"/v1/patients/{env.pid}/consent/withdraw", headers=env.pat)
    assert r.status_code == 200 and r.json()["consent_at"] is None
    r = post(env, [minute(2, T0 + timedelta(minutes=1))])
    assert r.status_code == 403 and r.json()["error"]["code"] == "consent_required"
    with env.Session() as s:
        assert s.scalars(select(m.AuditLog).where(m.AuditLog.action == "withdraw_consent")).first() is not None
    # recording consent again restores ingest
    assert env.client.post(f"/v1/patients/{env.pid}/consent", headers=env.pat).status_code == 200
    assert post(env, [minute(2, T0 + timedelta(minutes=1))]).status_code == 200


def delete_data(env, headers, json):
    return env.client.request("DELETE", f"/v1/patients/{env.pid}/data", headers=headers, json=json)


def test_delete_data_counts_confirm_self_only_audit_kept(env):
    post(env, [minute(i, T0 + timedelta(minutes=i)) for i in range(1, 6)] + [high_event(10, cause="c")])
    n_audit = count(env, m.AuditLog)
    assert delete_data(env, env.pat, {}).status_code == 422
    assert delete_data(env, env.pat, {"confirm": False}).status_code == 422
    assert delete_data(env, env.cg, {"confirm": True}).status_code == 403
    assert count(env, m.MinuteMetric) == 5
    r = delete_data(env, env.pat, {"confirm": True})
    assert r.status_code == 200
    d = r.json()["deleted"]
    assert d["minute_metrics"] == 5 and d["device_events"] == 1 and d["daily_metrics"] >= 1
    assert set(d) == {"daily_metrics", "baselines", "change_flags", "reports", "device_events", "minute_metrics"}
    for model in (m.MinuteMetric, m.DeviceEvent, m.DailyMetric, m.EventExtra, m.Escalation):
        assert count(env, model) == 0
    assert count(env, m.AuditLog) > n_audit
    with env.Session() as s:
        assert s.scalars(select(m.AuditLog).where(m.AuditLog.action == "delete_patient_data")).first() is not None


# ------------------------------------------------------------------ rate limits, secret

def test_login_rate_limit_429_standard_error_and_reset_on_success(env):
    for _ in range(10):
        assert env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": "nope"}).status_code == 401
    r = env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": PW})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    # other accounts are unaffected
    assert env.client.post("/v1/auth/login", json={"email": "pat@t.example", "password": PW}).status_code == 200
    # successful login clears the counter
    ratelimit.reset_all()
    for _ in range(5):
        env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": "nope"})
    assert env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": PW}).status_code == 200
    for _ in range(9):
        env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": "nope"})
    assert env.client.post("/v1/auth/login", json={"email": "cg@t.example", "password": PW}).status_code == 200


def test_ingest_rate_limit_per_user(env, monkeypatch):
    monkeypatch.setattr(ratelimit.ingest_requests, "limit", 3)
    for i in range(3):
        assert post(env, [minute(i + 1, T0 + timedelta(minutes=i))]).status_code == 200
    r = post(env, [minute(9, T0 + timedelta(minutes=9))])
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert post(env, [minute(9, T0 + timedelta(minutes=9))], headers=env.pat).status_code == 200


def test_weak_jwt_secret_warns(monkeypatch, caplog):
    monkeypatch.setattr(settings, "jwt_secret", "dev-only-change-me")
    with caplog.at_level(logging.WARNING):
        assert warn_if_weak_secret() is True
    assert any("JWT_SECRET" in r.message for r in caplog.records)
    monkeypatch.setattr(settings, "jwt_secret", "short")
    assert warn_if_weak_secret() is True
    monkeypatch.setattr(settings, "jwt_secret", "x" * 40)
    assert warn_if_weak_secret() is False


# ------------------------------------------------------------------ report activity timing

def _fill_days(env, peak_prev, peak_cur, end=date(2026, 4, 14)):
    hours_prev, hours_cur = [0] * 24, [0] * 24
    hours_prev[peak_prev], hours_prev[peak_prev + 1] = 30, 10
    hours_cur[peak_cur], hours_cur[peak_cur + 1] = 30, 20
    with env.Session() as s:
        for i in range(28):
            d = end - timedelta(days=27 - i)
            s.add(m.DailyMetric(patient_id=uuid.UUID(env.pid), day=d, valid=True, coverage_h=12.0,
                                active_min=40.0 + i % 3, strikes=900 + i, bouts=20, bout_median_s=60.0 + i % 2,
                                bout_longest_s=300.0, rhythm_cv_median=0.12 + 0.001 * (i % 2),
                                active_by_hour=hours_prev if i < 14 else hours_cur))
        # one invalid day with a loud hour that must be ignored
        s.commit()
    with env.Session() as s:
        p = s.get(m.Patient, uuid.UUID(env.pid))
        return reports_api._build_input(s, p, end)


def test_report_input_activity_timing_shift_later(env):
    inp = _fill_days(env, peak_prev=9, peak_cur=14)
    t = inp["activity_timing"]
    assert t["most_active_hours_local"] == ["14:00-15:00", "15:00-16:00"]
    assert t["shift_vs_baseline"] == "later"


def test_report_input_activity_timing_none_and_earlier_and_invalid_days_ignored(env):
    assert _fill_days(env, peak_prev=10, peak_cur=11)["activity_timing"]["shift_vs_baseline"] == "none"
    with env.Session() as s:
        for r in s.scalars(select(m.DailyMetric).where(m.DailyMetric.day >= date(2026, 4, 1))):
            r.active_by_hour = [0] * 7 + [50, 20] + [0] * 15  # peak at 07:00 on current-period days
        # invalid day with huge 20:00 hour: must not count
        d = s.get(m.DailyMetric, (uuid.UUID(env.pid), date(2026, 4, 14)))
        d.valid = False
        d.active_by_hour = [0] * 20 + [999] + [0] * 3
        s.commit()
    with env.Session() as s:
        t = reports_api._build_input(s, s.get(m.Patient, uuid.UUID(env.pid)), date(2026, 4, 14))["activity_timing"]
    assert t["most_active_hours_local"][0] == "07:00-08:00"
    assert t["shift_vs_baseline"] == "earlier"
