"""Fictional cases, scenario versions, injects, evidence and cohort-level releases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import APPROVAL_STATUSES, Base, CreatedAt, one_of, utcnow


class Case(CreatedAt, Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    victim_organization: Mapped[str] = mapped_column(String(200))
    fictional_disclaimer: Mapped[str] = mapped_column(Text)
    # Instructor-only framing (learning purpose, seeded ambiguity). Never serialized to students.
    instructor_overview: Mapped[str] = mapped_column(Text, default="")

    versions: Mapped[list[ScenarioVersion]] = relationship(back_populates="case")


class ScenarioVersion(CreatedAt, Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("case_id", "version_label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    version_label: Mapped[str] = mapped_column(String(16))
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    case: Mapped[Case] = relationship(back_populates="versions")
    injects: Mapped[list[Inject]] = relationship(
        back_populates="scenario_version", order_by="Inject.sequence"
    )
    evidence: Mapped[list[EvidenceItem]] = relationship(
        back_populates="scenario_version", order_by="EvidenceItem.sequence"
    )


class Inject(CreatedAt, Base):
    __tablename__ = "injects"
    __table_args__ = (
        UniqueConstraint("scenario_version_id", "code"),
        one_of("approval_status", APPROVAL_STATUSES),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_version_id: Mapped[int] = mapped_column(ForeignKey("scenario_versions.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    student_briefing: Mapped[str] = mapped_column(Text)
    instructor_notes: Mapped[str] = mapped_column(Text, default="")
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    # Restricts the inject's evidence to squads holding this track ("case:A", "site:418"); NULL = everyone.
    track: Mapped[str | None] = mapped_column(String(16))

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="injects")
    evidence: Mapped[list[EvidenceItem]] = relationship(back_populates="inject")


class EvidenceItem(CreatedAt, Base):
    """A synthetic record. ``inject_id`` NULL means part of the baseline packet released on case activation."""

    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("scenario_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_version_id: Mapped[int] = mapped_column(ForeignKey("scenario_versions.id", ondelete="CASCADE"))
    inject_id: Mapped[int | None] = mapped_column(ForeignKey("injects.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(64))
    # NULL when the source record carries no timestamp; never invented.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_timezone: Mapped[str | None] = mapped_column(String(64))
    observed_as_recorded: Mapped[str] = mapped_column(String(128))
    provenance: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    instructor_notes: Mapped[str] = mapped_column(Text, default="")

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="evidence")
    inject: Mapped[Inject | None] = relationship(back_populates="evidence")


class CohortCase(CreatedAt, Base):
    """Activating a scenario for a cohort releases its baseline evidence packet."""

    __tablename__ = "cohort_cases"
    __table_args__ = (UniqueConstraint("cohort_id", "scenario_version_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    scenario_version_id: Mapped[int] = mapped_column(ForeignKey("scenario_versions.id"))
    activated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario_version: Mapped[ScenarioVersion] = relationship()


class InjectRelease(CreatedAt, Base):
    __tablename__ = "inject_releases"
    __table_args__ = (UniqueConstraint("cohort_id", "inject_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    inject_id: Mapped[int] = mapped_column(ForeignKey("injects.id", ondelete="CASCADE"))
    released_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)
    # A withdrawn release hides the inject's evidence from students; the row is kept for history.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)
