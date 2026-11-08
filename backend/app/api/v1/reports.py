"""Report endpoints. Generation runs inline: numbers come from daily_metrics, Gemini (if a key is set)
only phrases them, the validator checks, and the template is the fallback (MASTER 14)."""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import numpy as np

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.deps import Access, ApiError, audit, get_current_user, get_membership, require_care_team
from backend.app.models import Baseline, DailyMetric, Patient, Report, User
from backend.app.reports.input_builder import build_report_input
from backend.app.reports.pipeline import generate_report
from backend.app.schemas import GenerateIn, ReportOut

router = APIRouter(tags=["reports"])

METRICS = ("active_min", "bout_median_s", "strikes", "rhythm_cv_median")


class _NoGemini:
    """Used when no GEMINI_API_KEY is configured: raising sends the pipeline to the template fallback."""
    model = "none"

    def generate(self, prompt, schema):
        raise RuntimeError("GEMINI_API_KEY not configured")


def get_gemini_client():
    if os.environ.get("GEMINI_API_KEY"):
        from backend.app.reports.gemini_client import GoogleGeminiClient
        return GoogleGeminiClient()
    return _NoGemini()


def _build_input(db: Session, patient: Patient, period_end: date) -> dict:
    first = period_end - timedelta(days=27)
    rows = {r.day: r for r in db.scalars(select(DailyMetric).where(
        DailyMetric.patient_id == patient.patient_id, DailyMetric.day >= first, DailyMetric.day <= period_end))}
    days = [first + timedelta(days=i) for i in range(28)]
    series = {m: np.array([
        float(getattr(rows[d], m)) if d in rows and rows[d].valid and getattr(rows[d], m) is not None else np.nan
        for d in days]) for m in METRICS}
    cov = np.array([rows[d].coverage_h if d in rows else np.nan for d in days])
    cur = [rows[d] for d in days[14:] if d in rows]
    events = dict(
        potential_fall_escalated=sum(r.events_potential_fall - r.events_cancelled for r in cur),
        potential_fall_cancelled=sum(r.events_cancelled for r in cur),
        help_requests=sum(r.help_presses for r in cur),
    )
    events["potential_fall_escalated"] = max(events["potential_fall_escalated"], 0)
    timing = _activity_timing(db, patient, rows, days)
    return build_report_input(series, coverage_h=cov, events=events, activity_timing=timing,
                              is_simulated=patient.is_simulated)


def _hour_sums(rows, days) -> list[float]:
    """Sum of active_by_hour (patient-local hours) over the valid days given."""
    tot = [0.0] * 24
    for d in days:
        r = rows.get(d)
        if r is not None and r.valid and r.active_by_hour and len(r.active_by_hour) == 24:
            for h, v in enumerate(r.active_by_hour):
                tot[h] += float(v or 0)
    return tot


def _activity_timing(db: Session, patient: Patient, rows: dict, days: list) -> dict:
    """Top-2 local hour windows of the current period and the shift of its peak hour versus the baseline
    period (active baseline range if there is one, else the previous 14 days). A shift of >= 2 hours counts."""
    cur = _hour_sums(rows, days[14:])
    if sum(cur) <= 0:
        return dict(most_active_hours_local=[], shift_vs_baseline="none")
    top = sorted(range(24), key=lambda h: (-cur[h], h))[:2]
    windows = [f"{h:02d}:00-{(h + 1) % 24:02d}:00" for h in top if cur[h] > 0]
    ref_rows, ref_days = rows, days[:14]
    bl = db.scalars(select(Baseline).where(Baseline.patient_id == patient.patient_id,
                                           Baseline.is_active.is_(True))).first()
    if bl is not None:
        ref_days = [bl.start_day + timedelta(days=i) for i in range((bl.end_day - bl.start_day).days + 1)]
        ref_rows = {r.day: r for r in db.scalars(select(DailyMetric).where(
            DailyMetric.patient_id == patient.patient_id, DailyMetric.day >= bl.start_day,
            DailyMetric.day <= bl.end_day))}
    ref = _hour_sums(ref_rows, ref_days)
    shift = "none"
    if sum(ref) > 0:
        delta = max(range(24), key=lambda h: (cur[h], -h)) - max(range(24), key=lambda h: (ref[h], -h))
        shift = "later" if delta >= 2 else "earlier" if delta <= -2 else "none"
    return dict(most_active_hours_local=windows, shift_vs_baseline=shift)


@router.get("/patients/{patient_id}/reports", response_model=list[ReportOut])
def list_reports(patient_id: uuid.UUID, acc: Access = Depends(require_care_team()), db: Session = Depends(get_db)):
    return list(db.scalars(select(Report).where(Report.patient_id == patient_id).order_by(Report.period_end.desc())))


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise ApiError(403, "forbidden", "You do not have access to this report")
    get_membership(db, user, r.patient_id)
    return r


def generate_for_period(db: Session, patient: Patient, period_end: date, client, actor_user_id=None) -> Report:
    """Shared by the endpoint and the scheduler. Idempotent: a finished report for the period is returned as is."""
    start = period_end - timedelta(days=13)
    existing = db.scalars(select(Report).where(Report.patient_id == patient.patient_id,
                                               Report.period_start == start)).first()
    # Only a successfully generated report is frozen. A pending / fallback / insufficient_data / failed one is
    # retried: more data may have arrived, or Gemini may be reachable now.
    if existing is not None and existing.status == "generated":
        return existing
    inp = _build_input(db, patient, period_end)
    res = generate_report(inp, client)
    fields = dict(status=res.status, input_json=inp, output_json=res.output.model_dump(mode="json"),
                  model=res.model, prompt_version=res.prompt_version, attempts=res.attempts,
                  validation=None if res.validation is None else {"passed": res.validation.ok,
                                                                  "issues": [str(i) for i in res.validation.issues]})
    if existing is None:
        existing = Report(patient_id=patient.patient_id, period_start=start, period_end=period_end,
                          is_simulated=patient.is_simulated, **fields)
        db.add(existing)
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
    audit(db, actor_user_id, "generate_report", patient.patient_id,
          {"period_end": str(period_end), "status": res.status, "scheduled": actor_user_id is None})
    db.commit()
    return existing


@router.post("/patients/{patient_id}/reports/generate", status_code=202)
def generate(patient_id: uuid.UUID, body: GenerateIn,
             acc: Access = Depends(require_care_team("clinician")), db: Session = Depends(get_db),
             client=Depends(get_gemini_client)):
    if acc.user.role not in ("clinician", "admin"):
        raise ApiError(403, "forbidden", "Only clinicians and admins can generate reports")
    rep = generate_for_period(db, db.get(Patient, patient_id), body.period_end, client, acc.user.user_id)
    return {"report_id": str(rep.report_id), "status": rep.status}
