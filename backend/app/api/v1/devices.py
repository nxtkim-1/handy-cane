from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.security import verify_secret
from backend.app.deps import ApiError, audit, get_current_user, get_membership
from backend.app.models import Device, DeviceAssignment, User
from backend.app.schemas import DeviceStatusOut, PairIn

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/pair", status_code=200)
def pair(body: PairIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_membership(db, user, body.patient_id, ("self", "caregiver"))
    dev = db.get(Device, body.device_id)
    if dev is None or not verify_secret(body.code, dev.secret_hash):
        raise ApiError(400, "bad_pairing_code", "Unknown device or wrong pairing code")
    now = datetime.now(timezone.utc)
    current = db.scalars(select(DeviceAssignment).where(DeviceAssignment.device_id == dev.device_id,
                                                        DeviceAssignment.valid_to.is_(None))).first()
    if current and current.patient_id == body.patient_id:
        return {"device_id": dev.device_id, "patient_id": str(body.patient_id), "status": "already_paired"}
    if current:
        current.valid_to = now
    db.add(DeviceAssignment(device_id=dev.device_id, patient_id=body.patient_id, valid_from=now))
    audit(db, user.user_id, "pair_device", body.patient_id, {"device_id": dev.device_id})
    db.commit()
    return {"device_id": dev.device_id, "patient_id": str(body.patient_id), "status": "paired"}


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
def device_status(device_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dev = db.get(Device, device_id)
    asg = db.scalars(select(DeviceAssignment).where(DeviceAssignment.device_id == device_id,
                                                    DeviceAssignment.valid_to.is_(None))).first()
    if dev is None or asg is None:
        raise ApiError(403, "forbidden", "You do not have access to this device")
    get_membership(db, user, asg.patient_id)
    return dev
