"""ORM models mirroring MASTER 12.2. Portable: Uuid/JSON/String types work on SQLite and PostgreSQL.

Enums are stored as strings (validated in the API layer); the real PostgreSQL DDL with native enums,
hypertables and continuous aggregates is in backend/migrations/001_init.sql.
Additions beyond 12.2 (also in the migration): ingest_batches.response_json (replay),
refresh_tokens (rotation/revocation, MASTER 16.1).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, Date, Float, ForeignKey, Index, Integer, LargeBinary,
                        SmallInteger, String, Text, UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.db import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # patient|caregiver|clinician|admin
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.user_id"), unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="America/Toronto")
    enrolled_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    report_anchor: Mapped[date] = mapped_column(Date, default=date.today)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    consent_version: Mapped[str | None] = mapped_column(Text)


class CareTeam(Base):
    __tablename__ = "care_team"
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    relation: Mapped[str] = mapped_column(String, nullable=False)  # self|caregiver|clinician
    can_dismiss_events: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.user_id"))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Device(Base):
    __tablename__ = "devices"
    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    hw_model: Mapped[str] = mapped_column(String, default="rpi4b")
    sensor_model: Mapped[str | None] = mapped_column(String)
    fw_version: Mapped[str | None] = mapped_column(String)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.device_id"), primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id"), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MinuteMetric(Base):
    __tablename__ = "minute_metrics"
    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    boot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    time_quality: Mapped[str] = mapped_column(String, nullable=False)
    n_samples: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mag_mean: Mapped[float | None] = mapped_column(Float)
    mag_std: Mapped[float | None] = mapped_column(Float)
    mag_max: Mapped[float | None] = mapped_column(Float)
    dyn_mean: Mapped[float | None] = mapped_column(Float)
    active_s: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    strike_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    strike_iv_mean: Mapped[float | None] = mapped_column(Float)
    strike_iv_cv: Mapped[float | None] = mapped_column(Float)
    upright_s: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    flat_s: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_impact_g: Mapped[float | None] = mapped_column(Float)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("device_id", "seq", name="minute_metrics_seq_uq"),)


class DeviceEvent(Base):
    __tablename__ = "device_events"
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_quality: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    peak_g: Mapped[float | None] = mapped_column(Float)
    tilt_deg: Mapped[float | None] = mapped_column(Float)
    still_s: Mapped[float | None] = mapped_column(Float)
    raw_snippet: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.user_id"))
    status_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="device_events_seq_uq"),
        Index("device_events_device_ts", "device_id", "ts"),
        Index("device_events_event_id", "event_id"),
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # patient-local date
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    coverage_h: Mapped[float] = mapped_column(Float, nullable=False)
    # Metric columns are NULL on invalid days: "no data" is never stored as zero.
    active_min: Mapped[float | None] = mapped_column(Float)
    strikes: Mapped[int | None] = mapped_column(Integer)
    bouts: Mapped[int | None] = mapped_column(Integer)
    bout_median_s: Mapped[float | None] = mapped_column(Float)
    bout_longest_s: Mapped[float | None] = mapped_column(Float)
    rhythm_cv_median: Mapped[float | None] = mapped_column(Float)
    active_by_hour: Mapped[list | None] = mapped_column(JSON)
    events_potential_fall: Mapped[int] = mapped_column(SmallInteger, default=0)
    events_cancelled: Mapped[int] = mapped_column(SmallInteger, default=0)
    help_presses: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Baseline(Base):
    __tablename__ = "baselines"
    baseline_id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id"), nullable=False)
    start_day: Mapped[date] = mapped_column(Date, nullable=False)
    end_day: Mapped[date] = mapped_column(Date, nullable=False)
    n_valid_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    set_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChangeFlag(Base):
    __tablename__ = "change_flags"
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id"), primary_key=True)
    metric: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.patient_id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    validation: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("patient_id", "period_start"),)


class IngestBatch(Base):
    __tablename__ = "ingest_batches"
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.user_id"))
    min_seq: Mapped[int | None] = mapped_column(BigInteger)
    max_seq: Mapped[int | None] = mapped_column(BigInteger)
    n_records: Mapped[int | None] = mapped_column(Integer)
    n_inserted: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict | None] = mapped_column(JSON)  # exact response, returned on replay
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict | None] = mapped_column(JSON)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.user_id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
