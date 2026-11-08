from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TimeQuality = Literal["synced", "corrected", "unsynced"]
EventKind = Literal["potential_fall", "help_request", "impact_only"]
EventOutcome = Literal["cancelled_by_user", "escalated", "acknowledged_on_cane"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth
class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


# ---- patients / me
class PatientOut(ORM):
    patient_id: uuid.UUID
    display_name: str
    timezone: str
    is_simulated: bool
    consent_at: Optional[datetime] = None


class LinkedPatient(PatientOut):
    relation: str
    can_dismiss_events: bool


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    patients: list[LinkedPatient]


class DailyOut(ORM):
    day: date
    valid: bool
    no_data: bool = False
    coverage_h: float
    active_min: Optional[float] = None
    strikes: Optional[int] = None
    bouts: Optional[int] = None
    bout_median_s: Optional[float] = None
    bout_longest_s: Optional[float] = None
    rhythm_cv_median: Optional[float] = None
    active_by_hour: Optional[list[int]] = None
    events_potential_fall: int = 0
    events_cancelled: int = 0
    help_presses: int = 0
    is_simulated: bool = False


class BaselineIn(BaseModel):
    start_day: date
    end_day: date


class BaselineOut(ORM):
    baseline_id: uuid.UUID
    start_day: date
    end_day: date
    n_valid_days: int
    stats: dict
    is_active: bool
    set_by: Optional[uuid.UUID] = None
    created_at: datetime


# ---- ingest
class IngestBatchIn(BaseModel):
    batch_id: uuid.UUID
    device_id: str = Field(min_length=1, max_length=64)
    fw_version: Optional[str] = None
    records: list[dict]  # validated one by one so a single bad record does not fail the batch


class MinuteRecordIn(BaseModel):
    type: Literal["minute"]
    seq: int = Field(ge=0)
    boot_id: uuid.UUID
    ts: datetime
    time_quality: TimeQuality
    n_samples: int = Field(ge=0, le=3300)
    mag_mean: Optional[float] = Field(default=None, ge=0, le=64)
    mag_std: Optional[float] = Field(default=None, ge=0, le=64)
    mag_max: Optional[float] = Field(default=None, ge=0, le=64)
    dyn_mean: Optional[float] = Field(default=None, ge=0, le=64)
    active_s: int = Field(ge=0, le=60)
    strike_count: int = Field(ge=0, le=300)
    strike_iv_mean: Optional[float] = Field(default=None, ge=0, le=60)
    strike_iv_cv: Optional[float] = Field(default=None, ge=0, le=20)
    upright_s: int = Field(ge=0, le=60)
    flat_s: int = Field(ge=0, le=60)
    max_impact_g: Optional[float] = Field(default=None, ge=0, le=64)


class EventRecordIn(BaseModel):
    type: Literal["event"]
    seq: int = Field(ge=0)
    event_id: uuid.UUID
    boot_id: uuid.UUID
    ts: datetime
    time_quality: TimeQuality
    kind: EventKind
    outcome: EventOutcome
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    peak_g: Optional[float] = Field(default=None, ge=0, le=64)
    tilt_deg: Optional[float] = Field(default=None, ge=0, le=180)
    still_s: Optional[float] = Field(default=None, ge=0, le=86400)
    raw_snippet_b64: Optional[str] = None


class Rejected(BaseModel):
    index: int
    seq: Optional[int] = None
    reason: str


class IngestOut(BaseModel):
    batch_id: uuid.UUID
    received: int
    inserted: int
    duplicates: int
    rejected: list[Rejected]
    server_max_seq: int


# ---- events
class EventOut(ORM):
    event_id: uuid.UUID
    device_id: str
    ts: datetime
    time_quality: str
    time_uncertain: bool = False
    kind: str
    outcome: str
    confidence: Optional[float] = None
    peak_g: Optional[float] = None
    tilt_deg: Optional[float] = None
    still_s: Optional[float] = None
    status: str
    status_reason: Optional[str] = None
    status_by: Optional[uuid.UUID] = None
    status_at: Optional[datetime] = None
    is_simulated: bool


class EventPatch(BaseModel):
    status: Literal["acknowledged", "dismissed"]
    reason: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)


# ---- devices
class PairIn(BaseModel):
    device_id: str
    code: str
    patient_id: uuid.UUID


class DeviceStatusOut(ORM):
    device_id: str
    sensor_model: Optional[str] = None
    fw_version: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    last_seq: int
    is_simulated: bool


# ---- reports (stubs)
class GenerateIn(BaseModel):
    period_end: date


class ReportOut(ORM):
    report_id: uuid.UUID
    patient_id: uuid.UUID
    period_start: date
    period_end: date
    status: str
    output_json: Optional[dict] = None
    prompt_version: str
    is_simulated: bool
    created_at: datetime
