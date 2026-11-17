"""Scenario release plans.

A release plan belongs to a scenario version and lists every piece of material that can reach a cohort:
evidence injects, staged document blocks, challenges (practice or scored), debriefs, and instructor-only
answer keys. Each item says who sees it and what opens it. The plan is approved as a whole (content
approval workflow); approval pins the plan's SHA-256 and locks the version. Each cohort that activates the
version gets its own per-item state, so instructors can release, hold, withdraw and re-release per cohort.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, one_of, utcnow

ITEM_TYPES = ("evidence_inject", "document", "document_block", "challenge", "debrief", "answer_key")
AUDIENCES = ("all_students", "investigator", "analyst", "staff")
TRIGGERS = ("manual", "scheduled", "lesson_gate", "after_item")
RELEASE_STATES = ("pending", "held", "released", "withdrawn")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


class ReleaseItem(CreatedAt, Base):
    __tablename__ = "release_items"
    __table_args__ = (
        UniqueConstraint("scenario_version_id", "code"),
        one_of("item_type", ITEM_TYPES),
        one_of("audience", AUDIENCES),
        one_of("trigger_type", TRIGGERS),
        one_of("trigger_day", DAYS),
        one_of("trigger_lesson_state", ("released", "taught")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_version_id: Mapped[int] = mapped_column(ForeignKey("scenario_versions.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    item_type: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    audience: Mapped[str] = mapped_column(String(16))
    # What opens the item
    trigger_type: Mapped[str] = mapped_column(String(16))
    trigger_day: Mapped[str | None] = mapped_column(String(3))  # course day, cohort-local
    trigger_time: Mapped[str | None] = mapped_column(String(5))  # HH:MM, cohort-local
    trigger_module_code: Mapped[str | None] = mapped_column(String(8))
    trigger_lesson_state: Mapped[str | None] = mapped_column(String(16))
    trigger_after_code: Mapped[str | None] = mapped_column(String(32))
    # Type-specific content
    inject_code: Mapped[str | None] = mapped_column(String(16))
    document_block: Mapped[str | None] = mapped_column(String(64))
    # Single controlled document (latest approved, clean version with this code).
    document_code: Mapped[str | None] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text, default="")
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    instrument_code: Mapped[str | None] = mapped_column(String(8))
    scored: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_for_code: Mapped[str | None] = mapped_column(String(32))
    instructor_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CohortReleaseItem(Base):
    __tablename__ = "cohort_release_items"
    __table_args__ = (UniqueConstraint("cohort_id", "item_id"), one_of("state", RELEASE_STATES))
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("release_items.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    # Why an automatic trigger could not release the item (e.g. awaiting approval); shown to instructors.
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
