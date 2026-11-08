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
from backend.app.models import DailyMetric, Patient, Report, User
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
    return build_report_input(series, coverage_h=cov, events=events, is_simulated=patient.is_simulated)


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


@router.post("/patients/{patient_id}/reports/generate", status_code=202)
def generate(patient_id: uuid.UUID, body: GenerateIn,
             acc: Access = Depends(require_care_team("clinician")), db: Session = Depends(get_db),
             client=Depends(get_gemini_client)):
    if acc.user.role not in ("clinician", "admin"):
        raise ApiError(403, "forbidden", "Only clinicians and admins can generate reports")
    start = body.period_end - timedelta(days=13)
    existing = db.scalars(select(Report).where(Report.patient_id == patient_id, Report.period_start == start)).first()
    if existing is not None and existing.status != "pending":
        return {"report_id": str(existing.report_id), "status": existing.status}  # idempotent
    p = db.get(Patient, patient_id)
    inp = _build_input(db, p, body.period_end)
    res = generate_report(inp, client)
    fields = dict(status=res.status, input_json=inp, output_json=res.output.model_dump(mode="json"),
                  model=res.model, prompt_version=res.prompt_version, attempts=res.attempts,
                  validation=None if res.validation is None else {"passed": res.validation.ok,
                                                                  "issues": [str(i) for i in res.validation.issues]})
    if existing is None:
        existing = Report(patient_id=patient_id, period_start=start, period_end=body.period_end,
                          is_simulated=p.is_simulated, **fields)
        db.add(existing)
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
    audit(db, acc.user.user_id, "generate_report", patient_id, {"period_end": str(body.period_end), "status": res.status})
    db.commit()
    return {"report_id": str(existing.report_id), "status": existing.status}
