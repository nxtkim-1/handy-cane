"""Report endpoints - STUBS. Generation (Gemini, validator, template fallback) is owned by backend/app/reports.

generate only records a `pending` row so the API shape in MASTER 13.5 works end to end.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.deps import Access, ApiError, audit, get_current_user, get_membership, require_care_team
from backend.app.models import Patient, Report, User
from backend.app.schemas import GenerateIn, ReportOut

router = APIRouter(tags=["reports"])


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
             acc: Access = Depends(require_care_team("clinician")), db: Session = Depends(get_db)):
    if acc.user.role not in ("clinician", "admin"):
        raise ApiError(403, "forbidden", "Only clinicians and admins can generate reports")
    start = body.period_end - timedelta(days=13)
    existing = db.scalars(select(Report).where(Report.patient_id == patient_id, Report.period_start == start)).first()
    if existing is None:
        p = db.get(Patient, patient_id)
        existing = Report(patient_id=patient_id, period_start=start, period_end=body.period_end, status="pending",
                          input_json={}, prompt_version="report-v1", is_simulated=p.is_simulated)
        db.add(existing)
        audit(db, acc.user.user_id, "generate_report", patient_id, {"period_end": str(body.period_end)})
        db.commit()
    return {"report_id": str(existing.report_id), "status": existing.status}
