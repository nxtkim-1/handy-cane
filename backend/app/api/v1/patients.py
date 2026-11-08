from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.app.analytics import stats as st
from backend.app.api.v1.me import linked_patients
from backend.app.core.db import get_db
from backend.app.deps import Access, ApiError, audit, get_current_user, require_care_team
from backend.app.metrics.daily import metric_series, refresh_analytics, set_baseline
from backend.app.models import (Baseline, ChangeFlag, DailyMetric, Device, DeviceAssignment, DeviceEvent, Patient,
                                Report, User)
from backend.app.schemas import BaselineIn, BaselineOut, DailyOut, EventOut, LinkedPatient

router = APIRouter(prefix="/patients", tags=["patients"])

ANY = ("self", "caregiver", "clinician")


def event_to_out(e: DeviceEvent) -> EventOut:
    out = EventOut.model_validate(e)
    out.time_uncertain = e.time_quality == "unsynced"
    return out


def patient_events_query(patient_id):
    """Events of devices while assigned to the patient."""
    return select(DeviceEvent).join(
        DeviceAssignment,
        and_(DeviceAssignment.device_id == DeviceEvent.device_id, DeviceAssignment.patient_id == patient_id,
             DeviceEvent.ts >= DeviceAssignment.valid_from,
             or_(DeviceAssignment.valid_to.is_(None), DeviceEvent.ts < DeviceAssignment.valid_to)))


def get_patient(db: Session, patient_id) -> Patient:
    p = db.get(Patient, patient_id)
    if p is None:  # unreachable for members (FK), kept defensive
        raise ApiError(404, "not_found", "Patient not found")
    return p


@router.get("", response_model=list[LinkedPatient])
def list_patients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ("caregiver", "clinician", "admin", "patient"):
        raise ApiError(403, "forbidden", "Not allowed")
    return linked_patients(db, user)


@router.get("/{patient_id}/daily", response_model=list[DailyOut])
def daily(patient_id: uuid.UUID, from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
          acc: Access = Depends(require_care_team()), db: Session = Depends(get_db)):
    """One entry per calendar day in [from, to]. Days without data are returned as no_data (null metrics), never zero."""
    q = select(DailyMetric).where(DailyMetric.patient_id == patient_id)
    if from_:
        q = q.where(DailyMetric.day >= from_)
    if to:
        q = q.where(DailyMetric.day <= to)
    rows = {r.day: r for r in db.scalars(q.order_by(DailyMetric.day))}
    if not rows and not (from_ and to):
        return []
    start, end = from_ or min(rows), to or max(rows)
    if (end - start).days > 400 or end < start:
        raise ApiError(422, "bad_range", "Range must be between 0 and 400 days")
    out = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        r = rows.get(d)
        out.append(DailyOut.model_validate(r) if r else DailyOut(day=d, valid=False, no_data=True, coverage_h=0.0))
    audit(db, acc.user.user_id, "view_daily", patient_id)
    db.commit()
    return out


@router.get("/{patient_id}/baseline", response_model=Optional[BaselineOut])
def get_baseline(patient_id: uuid.UUID, acc: Access = Depends(require_care_team()), db: Session = Depends(get_db)):
    return db.scalars(select(Baseline).where(Baseline.patient_id == patient_id, Baseline.is_active.is_(True))).first()


@router.post("/{patient_id}/baseline", response_model=BaselineOut, status_code=201)
def post_baseline(patient_id: uuid.UUID, body: BaselineIn, acc: Access = Depends(require_care_team("clinician")),
                  db: Session = Depends(get_db)):
    if body.end_day < body.start_day:
        raise ApiError(422, "bad_range", "end_day before start_day")
    bl = set_baseline(db, patient_id, body.start_day, body.end_day, set_by=acc.user.user_id)
    if bl is None:
        raise ApiError(422, "insufficient_data",
                       f"Need at least {st.CONFIG['baseline_min_days']} valid days in the range")
    refresh_analytics(db, patient_id)
    audit(db, acc.user.user_id, "set_baseline", patient_id,
          {"start_day": str(body.start_day), "end_day": str(body.end_day), "baseline_id": str(bl.baseline_id)})
    db.commit()
    return bl


@router.get("/{patient_id}/events", response_model=list[EventOut])
def list_events(patient_id: uuid.UUID, status: Optional[str] = Query(None, pattern="^(open|acknowledged|dismissed)$"),
                from_: Optional[datetime] = Query(None, alias="from"), to: Optional[datetime] = None,
                acc: Access = Depends(require_care_team()), db: Session = Depends(get_db)):
    q = patient_events_query(patient_id)
    if status:
        q = q.where(DeviceEvent.status == status)
    if from_:
        q = q.where(DeviceEvent.ts >= from_.astimezone(timezone.utc) if from_.tzinfo else DeviceEvent.ts >= from_.replace(tzinfo=timezone.utc))
    if to:
        q = q.where(DeviceEvent.ts <= to.astimezone(timezone.utc) if to.tzinfo else DeviceEvent.ts <= to.replace(tzinfo=timezone.utc))
    return [event_to_out(e) for e in db.scalars(q.order_by(DeviceEvent.ts.desc()))]


@router.get("/{patient_id}/overview")
def overview(patient_id: uuid.UUID, acc: Access = Depends(require_care_team()), db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    tz = ZoneInfo(p.timezone)
    now = datetime.now(timezone.utc)
    asg = db.scalars(select(DeviceAssignment).where(
        DeviceAssignment.patient_id == patient_id, DeviceAssignment.valid_to.is_(None))
        .order_by(DeviceAssignment.valid_from.desc())).first()
    dev = db.get(Device, asg.device_id) if asg else None
    today_d = now.astimezone(tz).date()
    t = db.get(DailyMetric, (patient_id, today_d))

    first, series = metric_series(db, patient_id, ("active_min",))
    last7 = {"active_min_median": None, "vs_baseline_z": None, "n_valid_days": 0}
    if first is not None:
        v = series["active_min"][~np.isnan(series["active_min"])][-7:]
        last7["n_valid_days"] = int(len(v))
        if len(v):
            med = float(np.median(v))
            last7["active_min_median"] = round(med, 1)
            bl = db.scalars(select(Baseline).where(Baseline.patient_id == patient_id,
                                                   Baseline.is_active.is_(True))).first()
            if bl and "active_min" in bl.stats:
                b = bl.stats["active_min"]
                z = st.robust_z(np.array([med]), st.Baseline(b["median"], b["mad"], b["n_days"]))[0]
                last7["vs_baseline_z"] = round(float(z), 2)

    open_events = db.scalar(select(func.count()).select_from(patient_events_query(patient_id)
                                                           .where(DeviceEvent.status == "open").subquery()))
    rep = db.scalars(select(Report).where(Report.patient_id == patient_id)
                     .order_by(Report.period_end.desc())).first()
    flags = {}
    for f in db.scalars(select(ChangeFlag).where(ChangeFlag.patient_id == patient_id).order_by(ChangeFlag.day)):
        flags.setdefault((f.metric, f.direction), f.day)
    audit(db, acc.user.user_id, "view_patient", patient_id)
    db.commit()
    return {
        "patient": {"patient_id": str(p.patient_id), "display_name": p.display_name, "is_simulated": p.is_simulated,
                    "timezone": p.timezone},
        "device": None if dev is None else {
            "device_id": dev.device_id, "last_seen_at": dev.last_seen_at, "sensor_model": dev.sensor_model,
            "is_simulated": dev.is_simulated, "unsynced_hint": False},
        "today": None if t is None else {"day": str(t.day), "valid_so_far": t.valid, "coverage_h": t.coverage_h,
                                         "active_min": t.active_min, "strikes": t.strikes},
        "last_7_valid_days": last7,
        "open_events": open_events,
        "latest_report": None if rep is None else {"report_id": str(rep.report_id), "period_end": str(rep.period_end),
                                                    "status": rep.status},
        "change_flags": [{"metric": m, "direction": d, "since": str(day)} for (m, d), day in flags.items()],
    }


@router.post("/{patient_id}/consent", status_code=200)
def record_consent(patient_id: uuid.UUID, version: str = "v1",
                   acc: Access = Depends(require_care_team("self", "caregiver")), db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    p.consent_at, p.consent_version = datetime.now(timezone.utc), version
    audit(db, acc.user.user_id, "record_consent", patient_id, {"version": version})
    db.commit()
    return {"patient_id": str(patient_id), "consent_at": p.consent_at, "consent_version": version}
