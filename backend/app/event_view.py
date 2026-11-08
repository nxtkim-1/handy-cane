"""Read-side helpers: events with extras + severity, sorting, per-patient open-event counts."""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.models import DeviceAssignment, DeviceEvent, EventExtra
from backend.app.schemas import EventOut
from backend.app.severity import RANK, severity_for


def patient_events_query(patient_id):
    """Events of devices while assigned to the patient.

    Events with an uncorrected clock (time_quality 'unsynced', the Pi has no RTC) carry a meaningless ts, so they
    belong to the patient who CURRENTLY has the device (open assignment); otherwise a real fall would be invisible.
    """
    in_window = and_(DeviceEvent.ts >= DeviceAssignment.valid_from,
                     or_(DeviceAssignment.valid_to.is_(None), DeviceEvent.ts < DeviceAssignment.valid_to))
    clock_unknown = and_(DeviceEvent.time_quality == "unsynced", DeviceAssignment.valid_to.is_(None))
    return select(DeviceEvent).join(
        DeviceAssignment,
        and_(DeviceAssignment.device_id == DeviceEvent.device_id, DeviceAssignment.patient_id == patient_id,
             or_(in_window, clock_unknown)))


def event_to_out(e: DeviceEvent, cause: str | None = None) -> EventOut:
    out = EventOut.model_validate(e)
    out.time_uncertain = e.time_quality == "unsynced"
    out.cause = cause
    out.severity, out.severity_reason = severity_for(
        SimpleNamespace(kind=e.kind, outcome=e.outcome, peak_g=e.peak_g, cause=cause))
    return out


def causes_for(db: Session, events: list[DeviceEvent]) -> dict:
    ids = [e.event_id for e in events]
    out: dict = {}
    for i in range(0, len(ids), 400):
        for x in db.scalars(select(EventExtra).where(EventExtra.event_id.in_(ids[i:i + 400]))):
            out[x.event_id] = x.cause
    return out


def events_to_out(db: Session, events: list[DeviceEvent]) -> list[EventOut]:
    causes = causes_for(db, events)
    return [event_to_out(e, causes.get(e.event_id)) for e in events]


def sort_events(outs: list[EventOut]) -> list[EventOut]:
    """Open before closed, then high>medium>low, then newest first."""
    outs = sorted(outs, key=lambda o: o.ts, reverse=True)  # stable: newest first within equal keys
    return sorted(outs, key=lambda o: (o.status != "open", RANK.get(o.severity, 1)))


def open_events_by_severity(db: Session, patient_id) -> dict:
    evs = list(db.scalars(patient_events_query(patient_id).where(DeviceEvent.status == "open")))
    counts = {"high": 0, "medium": 0, "low": 0}
    for o in events_to_out(db, evs):
        counts[o.severity] += 1
    return counts
