"""Caregiver escalation for high-severity open events.

A new high-severity event triggers one notification (optional Discord-compatible webhook, else a log line).
While the event stays open it is re-sent every ESCALATION_REPEAT_MINUTES, at most ESCALATION_MAX_REPEATS
notifications in total. Acknowledging or dismissing the event stops it. Every attempt is stored in
`escalations`. Sending never runs in the request path and a failure never propagates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.models import Escalation, DeviceEvent, EventExtra, Patient
from backend.app.severity import severity_for

log = logging.getLogger("smartcane.escalation")
HTTP_TIMEOUT_S = 5.0


def webhook_sender(url: str, text: str) -> None:
    """Default sender: POST {"content": text}; raises on any failure."""
    r = httpx.post(url, json={"content": text}, timeout=HTTP_TIMEOUT_S)
    r.raise_for_status()


_sender: Callable[[str, str], None] = webhook_sender


def set_sender(fn: Callable[[str, str], None] | None) -> None:
    """Inject the sender (tests use a fake). None restores the real webhook sender."""
    global _sender
    _sender = fn or webhook_sender


def build_message(event: DeviceEvent, patient: Patient, severity: str) -> str:
    try:
        local = event.ts.astimezone(ZoneInfo(patient.timezone))
    except Exception:
        local = event.ts
    kind = event.kind.replace("_", " ")
    return (f"[{severity.upper()}] {patient.display_name}: {kind} at {local.strftime('%Y-%m-%d %H:%M')} "
            f"({local.tzname()}). Open the Smart Cane app to respond.")


def _event_with_cause(db: Session, ev: DeviceEvent):
    ex = db.get(EventExtra, ev.event_id)
    ev.cause = ex.cause if ex else None  # transient attribute, read by severity_for
    return ev


def _send_and_record(db: Session, ev: DeviceEvent, attempt: int, now: datetime) -> None:
    patient = db.get(Patient, _patient_id(db, ev))
    ev = _event_with_cause(db, ev)
    sev, _ = severity_for(ev)
    text = build_message(ev, patient, sev)
    url = settings.escalation_webhook_url
    if not url:
        log.warning("ESCALATION (no webhook configured) attempt %d: %s", attempt, text)
        channel, ok, err = "log", False, "ESCALATION_WEBHOOK_URL not set"
    else:
        channel, ok, err = "webhook", True, None
        try:
            _sender(url, text)
        except Exception as e:  # never propagate
            ok, err = False, f"{type(e).__name__}: {e}"[:300]
            log.warning("Escalation webhook failed (attempt %d): %s", attempt, err)
    db.add(Escalation(event_id=ev.event_id, patient_id=patient.patient_id, channel=channel, sent_at=now, ok=ok,
                      attempt=attempt, error=err))
    db.commit()


def _patient_id(db: Session, ev: DeviceEvent):
    from backend.app.api.v1.events import patient_for_event
    return patient_for_event(db, ev)


def notify_new_events(factory: sessionmaker, event_ids: list) -> None:
    """Background task: first notification for freshly ingested high/open events."""
    for eid in event_ids:
        try:
            with factory() as db:
                ev = db.scalars(select(DeviceEvent).where(DeviceEvent.event_id == eid)).first()
                if ev is None or ev.status != "open":
                    continue
                if db.scalar(select(func.count()).select_from(Escalation).where(Escalation.event_id == eid)):
                    continue  # already notified
                _send_and_record(db, ev, 1, datetime.now(timezone.utc))
        except Exception:
            log.exception("escalation failed for event %s", eid)


def run_repeat_check(factory: sessionmaker, now: datetime | None = None) -> int:
    """Re-notify events still open after the repeat interval. Returns number of notifications sent."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    try:
        with factory() as db:
            rows = db.execute(select(Escalation.event_id, func.max(Escalation.attempt), func.max(Escalation.sent_at))
                              .group_by(Escalation.event_id)).all()
            for eid, attempts, last in rows:
                if attempts >= settings.escalation_max_repeats:
                    continue
                if now - last < timedelta(minutes=settings.escalation_repeat_minutes):
                    continue
                ev = db.scalars(select(DeviceEvent).where(DeviceEvent.event_id == eid)).first()
                if ev is None or ev.status != "open":
                    continue
                try:
                    _send_and_record(db, ev, attempts + 1, now)
                    sent += 1
                except Exception:
                    log.exception("escalation repeat failed for event %s", eid)
                    db.rollback()
    except Exception:
        log.exception("escalation repeat check failed")
    return sent
