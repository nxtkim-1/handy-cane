"""POST /v1/ingest/batches (MASTER 13.2, 7.4, 12.3, 17)."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.core.db import get_db
from backend.app.deps import ApiError, audit, get_current_user, get_membership
from backend.app.metrics.daily import run_daily_job
from backend.app import escalation, ratelimit
from backend.app.models import (Device, DeviceAssignment, DeviceEvent, EventExtra, IngestBatch, MinuteMetric, Patient,
                                User)
from backend.app.severity import severity_for
from backend.app.schemas import EventRecordIn, IngestBatchIn, MinuteRecordIn

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_SNIPPET_BYTES = 64 * 1024
CHUNK = 400


def _reason(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'record'}: {err['msg']}" for err in e.errors()[:4])


def _validate(rec: dict, now: datetime):
    """Returns (parsed_model, None) or (None, reason)."""
    kind = rec.get("type") if isinstance(rec, dict) else None
    model = {"minute": MinuteRecordIn, "event": EventRecordIn}.get(kind)
    if model is None:
        return None, "type must be 'minute' or 'event'"
    try:
        r = model.model_validate(rec)
    except ValidationError as e:
        return None, _reason(e)
    if r.ts.tzinfo is None:
        return None, "ts: must include a UTC offset"
    r.ts = r.ts.astimezone(timezone.utc)
    if r.ts > now + timedelta(days=1):
        return None, "ts: too far in the future"
    return r, None


def _existing_seqs(db: Session, device_id: str, seqs: list[int]) -> set[int]:
    found: set[int] = set()
    for i in range(0, len(seqs), CHUNK):
        part = seqs[i:i + CHUNK]
        for model in (MinuteMetric, DeviceEvent):
            found.update(db.scalars(select(model.seq).where(model.device_id == device_id, model.seq.in_(part))))
    return found


def _existing_minute_ts(db: Session, device_id: str, tss: list[datetime]) -> set[datetime]:
    found: set[datetime] = set()
    for i in range(0, len(tss), CHUNK):
        found.update(db.scalars(select(MinuteMetric.ts).where(MinuteMetric.device_id == device_id,
                                                              MinuteMetric.ts.in_(tss[i:i + CHUNK]))))
    return found


def _existing_event_ids(db: Session, ids: list) -> set:
    found: set = set()
    for i in range(0, len(ids), CHUNK):
        found.update(db.scalars(select(DeviceEvent.event_id).where(DeviceEvent.event_id.in_(ids[i:i + CHUNK]))))
    return found


def _process(body: IngestBatchIn, user: User, db: Session, new_high: list | None = None) -> dict:
    if new_high is not None:
        new_high.clear()
    if len(body.records) > settings.max_batch_records:
        raise ApiError(413, "batch_too_large", f"At most {settings.max_batch_records} records per batch")

    # Access: device must be currently paired to a patient the caller belongs to (self/caregiver).
    now = datetime.now(timezone.utc)
    device = db.get(Device, body.device_id)
    asg = db.scalars(select(DeviceAssignment).where(
        DeviceAssignment.device_id == body.device_id, DeviceAssignment.valid_to.is_(None))).first() if device else None
    if device is None or asg is None:
        raise ApiError(403, "device_not_paired", "Device is not paired to a patient")
    get_membership(db, user, asg.patient_id, ("self", "caregiver"))

    prior = db.get(IngestBatch, body.batch_id)
    if prior is not None:
        if prior.device_id != body.device_id:
            raise ApiError(409, "batch_id_conflict", "batch_id was already used for another device")
        return prior.response_json  # replay: identical response, no new rows

    patient = db.get(Patient, asg.patient_id)
    if patient.consent_at is None:
        raise ApiError(403, "consent_required", "Patient consent has not been recorded")

    rejected: list[dict] = []
    parsed: list = []
    seen_seq: set[int] = set()
    raws: dict = {}
    for i, rec in enumerate(body.records):
        r, why = _validate(rec, now)
        if why:
            seq = rec.get("seq") if isinstance(rec, dict) and isinstance(rec.get("seq"), int) else None
            rejected.append({"index": i, "seq": seq, "reason": why})
            continue
        if r.type == "event" and r.raw_snippet_b64:
            try:
                raw = base64.b64decode(r.raw_snippet_b64, validate=True)
                if len(raw) > MAX_SNIPPET_BYTES:
                    raise ValueError
                raws[r.event_id] = raw
            except (binascii.Error, ValueError):
                rejected.append({"index": i, "seq": r.seq, "reason": "raw_snippet_b64: invalid or too large"})
                continue
        parsed.append((i, r))

    db_seqs = _existing_seqs(db, body.device_id, sorted({r.seq for _, r in parsed}))
    db_ts = _existing_minute_ts(db, body.device_id, [r.ts for _, r in parsed if r.type == "minute"])
    db_eids = _existing_event_ids(db, [r.event_id for _, r in parsed if r.type == "event"])

    inserted = duplicates = 0
    touched: list[datetime] = []
    sim = device.is_simulated
    for _, r in parsed:
        dup = r.seq in db_seqs or r.seq in seen_seq or (r.type == "minute" and r.ts in db_ts) \
            or (r.type == "event" and r.event_id in db_eids)
        if dup:
            duplicates += 1
            continue
        seen_seq.add(r.seq)
        d = r.model_dump(exclude={"type", "raw_snippet_b64", "cause", "source"})
        if r.type == "minute":
            db.add(MinuteMetric(device_id=body.device_id, is_simulated=sim, **d))
            db_ts.add(r.ts)
        else:
            d.pop("boot_id")  # boot_id is kept on minute rows only (MASTER 12.2)
            db.add(DeviceEvent(device_id=body.device_id, is_simulated=sim, raw_snippet=raws.get(r.event_id), **d))
            db_eids.add(r.event_id)
            if r.cause is not None or r.source is not None:
                db.add(EventExtra(event_id=r.event_id, cause=r.cause, source=r.source))
            if new_high is not None and severity_for(r)[0] == "high":  # new events are always status 'open'
                new_high.append(r.event_id)
        touched.append(r.ts)
        inserted += 1

    max_seen = max([r.seq for _, r in parsed], default=0)
    device.last_seq = max(device.last_seq or 0, max_seen)
    device.last_seen_at = now
    if body.fw_version:
        device.fw_version = body.fw_version
    response = {"batch_id": str(body.batch_id), "received": len(body.records), "inserted": inserted,
                "duplicates": duplicates, "rejected": rejected, "server_max_seq": device.last_seq}
    db.add(IngestBatch(batch_id=body.batch_id, device_id=body.device_id, uploaded_by=user.user_id,
                       min_seq=min([r.seq for _, r in parsed], default=None), max_seq=max_seen or None,
                       n_records=len(body.records), n_inserted=inserted, response_json=response))
    db.flush()
    if touched:
        tz = ZoneInfo(patient.timezone)
        run_daily_job(db, patient.patient_id, {t.astimezone(tz).date() for t in touched})  # commits
    else:
        db.commit()
    return response


@router.post("/batches")
def ingest_batches(body: IngestBatchIn, request: Request, background: BackgroundTasks,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not ratelimit.ingest_requests.allow(str(user.user_id)):
        raise ApiError(429, "rate_limited", "Too many ingest requests; slow down")
    new_high: list = []
    try:
        resp = _process(body, user, db, new_high)
    except IntegrityError:
        # Concurrent upload of overlapping data won the race: retry once; dedup will now see their rows.
        db.rollback()
        resp = _process(body, user, db, new_high)
    if new_high:  # runs after the response is sent; own session; failures are logged, never raised
        background.add_task(escalation.notify_new_events, sessionmaker(bind=db.get_bind()), list(new_high))
    return resp
