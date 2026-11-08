from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.deps import get_current_user
from backend.app.models import CareTeam, Patient, User
from backend.app.schemas import LinkedPatient, MeOut, PatientOut

router = APIRouter(tags=["me"])


def linked_patients(db: Session, user: User) -> list[LinkedPatient]:
    rows = db.execute(
        select(Patient, CareTeam).join(CareTeam, CareTeam.patient_id == Patient.patient_id)
        .where(CareTeam.user_id == user.user_id, CareTeam.revoked_at.is_(None))
        .order_by(Patient.display_name)).all()
    return [LinkedPatient(**PatientOut.model_validate(p).model_dump(), relation=ct.relation,
                          can_dismiss_events=ct.can_dismiss_events) for p, ct in rows]


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return MeOut(user_id=user.user_id, email=user.email, display_name=user.display_name, role=user.role,
                 patients=linked_patients(db, user))
