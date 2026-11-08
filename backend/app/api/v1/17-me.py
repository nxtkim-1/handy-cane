from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.deps import get_current_user
from backend.app.event_view import open_events_by_severity
from backend.app.models import CareTeam, ChangeFlag, Device, DeviceAssignment, Patient, User
from backend.app.schemas import LinkedPatient, MeOut, PatientOut

router = APIRouter(tags=["me"])


def linked_patients(db: Session, user: User) -> list[LinkedPatient]:
    rows = db.execute(
        select(Patient, CareTeam).join(CareTeam, CareTeam.patient_id == Patient.patient_id)
        .where(CareTeam.user_id == user.user_id, CareTeam.revoked_at.is_(None))
        .order_by(Patient.display_name)).all()
    now = datetime.now(timezone.utc)
    out = []
    for p, ct in rows:
        by_sev = open_events_by_severity(db, p.patient_id)
        last = db.scalar(select(func.max(Device.last_seen_at)).join(
            DeviceAssignment, DeviceAssignment.device_id == Device.device_id).where(
            DeviceAssignment.patient_id == p.patient_id, DeviceAssignment.valid_to.is_(None)))
        flag = db.scalar(select(func.count()).select_from(ChangeFlag).where(ChangeFlag.patient_id == p.patient_id))
        out.append(LinkedPatient(
            **PatientOut.model_validate(p).model_dump(), relation=ct.relation,
            can_dismiss_events=ct.can_dismiss_events, open_events=sum(by_sev.values()),
            open_high_events=by_sev["high"], last_sync_at=last, sustained_change=bool(flag),
            stale_sync=last is None or now - last > timedelta(hours=48)))
    return out


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return MeOut(user_id=user.user_id, email=user.email, display_name=user.display_name, role=user.role,
                 patients=linked_patients(db, user))
