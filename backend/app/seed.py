"""Seed demo accounts and 8 weeks of SIMULATED history.   python -m backend.app.seed [--reset]

Daily targets come from backend/sim/generate.py (missing days stay missing). They are expanded into per-minute
records, then pushed through the same daily-metrics job as real data. Everything is flagged is_simulated.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.core.db import SessionLocal, engine, init_db
from backend.app.core.security import hash_secret
from backend.app.metrics.daily import run_daily_job
from backend.sim.generate import simulate

TZ = "America/Toronto"
DEVICE_ID = "cane-sim01"
PAIRING_CODE = "SIM-0001"
PASSWORD = "demo-password-1"
ACCOUNTS = {
    "clinician": ("clinician@demo.example", "Dr. Demo Clinician", "clinician"),
    "other_clinician": ("clinician2@demo.example", "Dr. Other Clinician", "clinician"),
    "patient": ("patient@demo.example", "Demo Patient", "patient"),
    "caregiver": ("caregiver@demo.example", "Demo Caregiver", "caregiver"),
}


def _user(db: Session, key: str) -> m.User:
    email, name, role = ACCOUNTS[key]
    u = db.scalars(select(m.User).where(m.User.email == email)).first()
    if u is None:
        u = m.User(email=email, display_name=name, role=role, password_hash=hash_secret(PASSWORD))
        db.add(u)
        db.flush()
    return u


def _day_minutes(rng, day_utc_starts: list[datetime], active_min: float, bout_s: float, partial: bool):
    """Per-minute dicts (without device/seq fields) for one local day, 08:00-20:00 covered."""
    n_min = 240 if partial else 720
    start = day_utc_starts[0]
    rows = [dict(active_s=0, strike_count=0, strike_iv_mean=None, strike_iv_cv=None, upright_s=60) for _ in range(n_min)]
    target_bout_min = max(1.0, active_min * 60 / 48.0)
    mean_len = max(1.0, 2 * bout_s / 60.0)  # minute records cannot resolve <60 s; scaled so decline stays visible
    used, i = 0.0, int(rng.integers(0, 40))
    while used < target_bout_min and i < n_min - 4:
        L = int(max(1, rng.poisson(mean_len)))
        L = min(L, n_min - i, int(np.ceil(target_bout_min - used)) + 1)
        for k in range(L):
            rows[i + k] = dict(active_s=int(rng.integers(40, 58)), strike_count=int(rng.integers(25, 46)),
                               strike_iv_mean=float(rng.normal(1.1, 0.05)),
                               strike_iv_cv=float(abs(rng.normal(0.13, 0.03))), upright_s=58)
        used += L
        i += L + int(rng.integers(3, 12))
    return start, rows


def load_history(db: Session, patient: m.Patient, device: m.Device, seed: int = 7) -> int:
    sim = simulate(seed=seed)
    n = sim["config"]["days"]
    tz = ZoneInfo(TZ)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    first_day = today - timedelta(days=n)  # history ends yesterday
    rng = np.random.default_rng(seed)
    boot = uuid.uuid4()
    seq, batch = 0, []
    partial_day = 10  # a short-coverage day: stored but invalid, never counted as zero
    for d in range(n):
        a, b = sim["active_min"][d], sim["bout_median_s"][d]
        if np.isnan(a):
            continue  # cane off: no records at all
        local_day = first_day + timedelta(days=d)
        start_local = datetime(local_day.year, local_day.month, local_day.day, 8, tzinfo=tz)
        start, rows = _day_minutes(rng, [start_local.astimezone(timezone.utc)], float(a), float(b), d == partial_day)
        for k, r in enumerate(rows):
            seq += 1
            batch.append(dict(device_id=device.device_id, ts=start + timedelta(minutes=k), seq=seq, boot_id=boot,
                              time_quality="synced", n_samples=int(rng.integers(2950, 3001)),
                              mag_mean=1.01, mag_std=0.05, mag_max=1.5, dyn_mean=0.02, flat_s=0, max_impact_g=1.5,
                              is_simulated=True, ingested_at=datetime.now(timezone.utc), **r))
        if len(batch) > 5000:
            db.execute(insert(m.MinuteMetric), batch)
            batch = []
    if batch:
        db.execute(insert(m.MinuteMetric), batch)

    def ev(days_ago: int, kind: str, outcome: str, peak: float):
        nonlocal seq
        seq += 1
        ts = datetime.combine(today - timedelta(days=days_ago), datetime.min.time(), tzinfo=tz).replace(hour=14)
        db.add(m.DeviceEvent(event_id=uuid.uuid4(), ts=ts.astimezone(timezone.utc), device_id=device.device_id,
                             seq=seq, time_quality="synced", kind=kind, outcome=outcome, confidence=0.6,
                             peak_g=peak, tilt_deg=80, still_s=11.0, is_simulated=True))
    ev(3, "potential_fall", "cancelled_by_user", 4.1)
    ev(10, "help_request", "acknowledged_on_cane", 1.2)
    ev(20, "impact_only", "cancelled_by_user", 3.2)
    device.last_seq, device.last_seen_at = seq, datetime.now(timezone.utc)
    db.flush()
    run_daily_job(db, patient.patient_id)
    return seq


def seed(db: Session, reset: bool = False) -> dict:
    existing = db.scalars(select(m.Patient).where(m.Patient.display_name == "Demo Patient (simulated)")).first()
    if existing and not reset:
        return {"status": "already_seeded", "patient_id": str(existing.patient_id)}
    if existing and reset:
        pid = existing.patient_id
        for model in (m.ChangeFlag, m.Baseline, m.DailyMetric, m.Report):
            db.execute(delete(model).where(model.patient_id == pid))
        db.execute(delete(m.DeviceEvent).where(m.DeviceEvent.device_id == DEVICE_ID))
        db.execute(delete(m.MinuteMetric).where(m.MinuteMetric.device_id == DEVICE_ID))
        db.execute(delete(m.IngestBatch).where(m.IngestBatch.device_id == DEVICE_ID))
        db.execute(delete(m.DeviceAssignment).where(m.DeviceAssignment.device_id == DEVICE_ID))
        db.execute(delete(m.CareTeam).where(m.CareTeam.patient_id == pid))
        db.execute(delete(m.Patient).where(m.Patient.patient_id == pid))
        db.execute(delete(m.Device).where(m.Device.device_id == DEVICE_ID))
        db.flush()

    users = {k: _user(db, k) for k in ACCOUNTS}
    n_days = simulate()["config"]["days"]
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(TZ)).date()
    patient = m.Patient(user_id=users["patient"].user_id, display_name="Demo Patient (simulated)", timezone=TZ,
                        report_anchor=today - timedelta(days=n_days), is_simulated=True,
                        consent_at=datetime.now(timezone.utc), consent_version="demo-v1")
    db.add(patient)
    db.flush()
    for key, rel, dismiss in (("patient", "self", True), ("caregiver", "caregiver", False),
                              ("clinician", "clinician", True)):
        db.add(m.CareTeam(patient_id=patient.patient_id, user_id=users[key].user_id, relation=rel,
                          can_dismiss_events=dismiss, granted_by=users["patient"].user_id))
    device = m.Device(device_id=DEVICE_ID, sensor_model="ADXL345", fw_version="sim", is_simulated=True,
                      secret_hash=hash_secret(PAIRING_CODE))
    db.add(device)
    db.flush()
    start = datetime.combine(today - timedelta(days=n_days + 1), datetime.min.time(), tzinfo=timezone.utc)
    db.add(m.DeviceAssignment(device_id=DEVICE_ID, patient_id=patient.patient_id, valid_from=start))
    db.flush()
    n = load_history(db, patient, device)
    db.commit()
    return {"status": "seeded", "patient_id": str(patient.patient_id), "records": n, "device_id": DEVICE_ID,
            "pairing_code": PAIRING_CODE, "password": PASSWORD, "accounts": [a[0] for a in ACCOUNTS.values()]}


if __name__ == "__main__":
    init_db(engine)
    with SessionLocal() as s:
        print(seed(s, reset="--reset" in sys.argv))
