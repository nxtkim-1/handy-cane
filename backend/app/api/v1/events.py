from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.event_view import events_to_out
from backend.app.core.db import get_db
from backend.app.deps import ApiError, audit, get_current_user, get_membership
from backend.app.models import DeviceAssignment, DeviceEvent, User
from backend.app.schemas import EventOut, EventPatch

router = APIRouter(prefix="/events", tags=["events"])


def patient_for_event(db: Session, ev: DeviceEvent):
    a = db.scalars(select(DeviceAssignment).where(
        DeviceAssignment.device_id == ev.device_id, DeviceAssignment.valid_from <= ev.ts,
        or_(DeviceAssignment.valid_to.is_(None), DeviceAssignment.valid_to > ev.ts))).first()
    return a.patient_id if a else None


@router.patch("/{event_id}", response_model=EventOut)
def patch_event(event_id: uuid.UUID, body: EventPatch, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Acknowledge or dismiss. Events are never deleted; every change is audited (MASTER 13.4)."""
    ev = db.scalars(select(DeviceEvent).where(DeviceEvent.event_id == event_id)).first()
    # Same 403 whether the event does not exist or is not yours, so ids cannot be probed.
    pid = patient_for_event(db, ev) if ev else None
    if pid is None:
        raise ApiError(403, "forbidden", "You do not have access to this event")
    acc = get_membership(db, user, pid)
    if body.status == "dismissed":
        if not (acc.can_dismiss_events or acc.relation == "self"):
            raise ApiError(403, "cannot_dismiss", "Not permitted to dismiss events for this patient")
        if not body.reason:
            raise ApiError(422, "reason_required", "A reason is required to dismiss an event")
    if ev.status == "dismissed":
        raise ApiError(409, "already_dismissed", "Dismissed events cannot be changed")
    old = ev.status
    ev.status, ev.status_reason = body.status, body.reason
    ev.status_by, ev.status_at = user.user_id, datetime.now(timezone.utc)
    audit(db, user.user_id, "dismiss_event" if body.status == "dismissed" else "acknowledge_event", pid,
          {"event_id": str(event_id), "from": old, "to": body.status, "reason": body.reason, "note": body.note})
    db.commit()
    return events_to_out(db, [ev])[0]
