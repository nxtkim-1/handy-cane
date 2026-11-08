"""Background jobs (APScheduler). Each job is a plain function so tests call it directly.

Started from the FastAPI lifespan only when SCHEDULER_ENABLED is true. Single-process: run one API worker.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import sessionmaker

from backend.app import escalation
from backend.app.core import db as dbmod
from backend.app.models import Patient, RefreshToken

log = logging.getLogger("smartcane.scheduler")


def _factory(factory: sessionmaker | None) -> sessionmaker:
    return factory or dbmod.SessionLocal


def escalation_check_job(factory: sessionmaker | None = None, now: datetime | None = None) -> int:
    """Every minute: re-notify events still open after the repeat interval."""
    return escalation.run_repeat_check(_factory(factory), now)


def due_report_period_end(patient: Patient, now: datetime):
    """period_end if a 14-day period (report_anchor + 14k days) ended yesterday in the patient's local time."""
    yesterday = now.astimezone(ZoneInfo(patient.timezone)).date() - timedelta(days=1)
    start = yesterday - timedelta(days=13)
    k = (start - patient.report_anchor).days
    return yesterday if k >= 0 and k % 14 == 0 else None


def daily_reports_job(factory: sessionmaker | None = None, now: datetime | None = None, client=None) -> list:
    """Daily 03:00 UTC: generate reports for periods that ended yesterday (idempotent). Returns report ids."""
    from backend.app.api.v1.reports import generate_for_period, get_gemini_client
    now = now or datetime.now(timezone.utc)
    client = client or get_gemini_client()  # same Gemini-or-template selection as the endpoint
    made = []
    with _factory(factory)() as db:
        for p in list(db.scalars(select(Patient))):
            try:
                end = due_report_period_end(p, now)
                if end is None:
                    continue
                made.append(str(generate_for_period(db, p, end, client).report_id))
            except Exception:
                db.rollback()
                log.exception("scheduled report failed for patient %s", p.patient_id)
    return made


def purge_tokens_job(factory: sessionmaker | None = None, now: datetime | None = None) -> int:
    """Daily: delete expired or revoked refresh tokens."""
    now = now or datetime.now(timezone.utc)
    with _factory(factory)() as db:
        n = db.execute(delete(RefreshToken).where(
            or_(RefreshToken.expires_at < now, RefreshToken.revoked_at.is_not(None)))).rowcount
        db.commit()
    return n


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sch = BackgroundScheduler(timezone="UTC")
    sch.add_job(escalation_check_job, "interval", minutes=1, id="escalation_check", max_instances=1, coalesce=True)
    sch.add_job(daily_reports_job, CronTrigger(hour=3, minute=0, timezone="UTC"), id="daily_reports")
    sch.add_job(purge_tokens_job, CronTrigger(hour=3, minute=30, timezone="UTC"), id="purge_tokens")
    sch.start()
    return sch
