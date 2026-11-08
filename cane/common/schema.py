"""Record contract shared by the cane, phone and backend (MASTER.md 7.4, 13.2)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal, Optional

TimeQuality = Literal["synced", "corrected", "unsynced"]
EventKind = Literal["potential_fall", "help_request", "impact_only"]
EventOutcome = Literal["cancelled_by_user", "escalated", "acknowledged_on_cane"]

SAMPLE_RATE_HZ = 50
EXPECTED_SAMPLES_PER_MIN = SAMPLE_RATE_HZ * 60  # 3000


@dataclass
class MinuteRecord:
    seq: int
    boot_id: str
    ts: str  # ISO-8601 UTC, start of minute
    time_quality: TimeQuality
    n_samples: int
    mag_mean: float
    mag_std: float
    mag_max: float
    dyn_mean: float
    active_s: int
    strike_count: int
    strike_iv_mean: Optional[float]
    strike_iv_cv: Optional[float]
    upright_s: int
    flat_s: int
    max_impact_g: float
    type: str = "minute"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EventRecord:
    seq: int
    event_id: str
    boot_id: str
    ts: str
    time_quality: TimeQuality
    kind: EventKind
    outcome: EventOutcome
    confidence: float
    peak_g: float
    tilt_deg: float
    still_s: float
    raw_snippet_b64: Optional[str] = None
    type: str = "event"

    def to_dict(self) -> dict:
        return asdict(self)
