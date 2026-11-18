from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.release import TRACK_PATTERN

ItemType = Literal["evidence_inject", "document", "document_block", "challenge", "debrief", "answer_key"]
Audience = Literal["all_students", "investigator", "analyst", "staff"]
Trigger = Literal["manual", "scheduled", "lesson_gate", "after_item"]
CODE = r"^[A-Z0-9][A-Z0-9-]{1,31}$"


class ReleaseItemIn(BaseModel):
    code: str = Field(pattern=CODE)
    sequence: int = Field(default=0, ge=0, le=10_000)
    item_type: ItemType
    title: str = Field(min_length=1, max_length=200)
    audience: Audience = "all_students"
    trigger_type: Trigger = "manual"
    trigger_day: Literal["Mon", "Tue", "Wed", "Thu", "Fri"] | None = None
    trigger_time: str | None = Field(default=None, max_length=5)
    trigger_module_code: str | None = Field(default=None, pattern=r"^M\d{2}$")
    trigger_lesson_state: Literal["released", "taught"] | None = None
    trigger_after_code: str | None = Field(default=None, max_length=32)
    inject_code: str | None = Field(default=None, max_length=16)
    document_block: str | None = Field(default=None, max_length=64)
    document_code: str | None = Field(default=None, max_length=32)
    body: str = Field(default="", max_length=20_000)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=600)
    instrument_code: str | None = Field(default=None, max_length=8)
    scored: bool = False
    answer_for_code: str | None = Field(default=None, max_length=32)
    instructor_notes: str = Field(default="", max_length=8_000)
    # Restrict to squads holding this track, e.g. "case:A" or "site:418"; empty = every student.
    track: str | None = Field(default=None, pattern=TRACK_PATTERN)

    @field_validator("track", mode="before")
    @classmethod
    def _track(cls, v: str | None) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return None
        kind, _, label = v.strip().partition(":")
        return f"{kind.lower()}:{label.upper()}"

    @field_validator(
        "code", "trigger_after_code", "answer_for_code", "inject_code", "document_code", mode="before"
    )
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if isinstance(v, str) else v


class ReleaseItemOut(ReleaseItemIn):
    id: int


class ScenarioVersionOut(BaseModel):
    id: int
    case_code: str
    case_title: str
    version_label: str
    approval_status: str
    locked: bool
    item_count: int
    pending_approval_id: int | None
    cohorts_using: list[str]


class Option(BaseModel):
    code: str
    label: str


class ScenarioVersionDetailOut(ScenarioVersionOut):
    plan_sha256: str
    items: list[ReleaseItemOut]
    injects: list[Option]
    document_blocks: list[Option]
    instruments: list[Option]
    modules: list[Option]


class CloneIn(BaseModel):
    version_label: str = Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z.\-]{0,15}$")


class ActivateIn(BaseModel):
    scenario_version_id: int


class ActionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CohortReleaseOut(BaseModel):
    item_id: int
    code: str
    sequence: int
    item_type: str
    title: str
    audience: str
    trigger: str
    state: str
    due_at: datetime | None
    released_at: datetime | None
    released_by: str | None
    withdrawn_at: datetime | None
    reason: str | None
    blocked_reason: str | None
    scored: bool
    preview: str
    instructor_notes: str
    track: str | None = None


class CohortPlanOut(BaseModel):
    cohort_id: int
    cohort_code: str
    timezone: str
    case_code: str | None
    scenario_version: str | None
    approval_status: str | None
    can_control: bool
    items: list[CohortReleaseOut]


class StudentChallengeOut(BaseModel):
    code: str
    item_type: str
    title: str
    body: str
    time_limit_minutes: int | None
    instrument_code: str | None
    scored: bool
    released_at: datetime | None
