"""Output schema, exactly as MASTER.md 14.5."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = "This report describes cane-use patterns and is not a medical diagnosis."


class Finding(BaseModel):
    metric_key: str
    statement: str
    direction: Literal["up", "down", "stable", "unclear"]


class SafetyNote(BaseModel):
    statement: str
    source: Literal["events", "metrics", "completeness"]


class ReportOutput(BaseModel):
    overall_summary: str = Field(description="3-4 sentences, plain language, no diagnosis")
    activity_overview: str
    mobility_trends: list[Finding] = Field(max_length=8)
    changes_vs_previous: list[Finding] = Field(max_length=8)
    safety_concerns: list[SafetyNote] = Field(max_length=5)
    areas_to_monitor: list[str] = Field(max_length=5)
    data_reliability: str
    patient_friendly_summary: str = Field(description="Grade 6 reading level, 2-3 sentences")
    disclaimer_ack: Literal["This report describes cane-use patterns and is not a medical diagnosis."]
