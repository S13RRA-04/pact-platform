"""Curriculum catalog: immutable course versions imported from the source workbook.

Relationships between curriculum items (module->objective, objective->instrument, ...) are stored
*per source sheet* in ``curriculum_links``. Conflicting sheets are preserved side by side and reported
by the importer; nothing reconciles them automatically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import APPROVAL_STATUSES, PATHWAYS, Base, CreatedAt, one_of


class Course(CreatedAt, Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class CourseVersion(CreatedAt, Base):
    """A course version is immutable once locked; new source content creates a new version."""

    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "source_sha256"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    version_label: Mapped[str] = mapped_column(String(32))
    source_filename: Mapped[str] = mapped_column(String(256))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_document_status: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="provisional")
    locked: Mapped[bool] = mapped_column(Boolean, default=True)

    course: Mapped[Course] = relationship()


class _VersionScoped:
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_versions.id", ondelete="CASCADE"))


class Task(CreatedAt, _VersionScoped, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("course_version_id", "code"), one_of("pathway", PATHWAYS))
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    pathway: Mapped[str] = mapped_column(String(16))
    statement: Mapped[str] = mapped_column(Text)
    task_source: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(64))
    source_row: Mapped[dict[str, Any]]


class Objective(CreatedAt, _VersionScoped, Base):
    __tablename__ = "objectives"
    __table_args__ = (UniqueConstraint("course_version_id", "code"), one_of("pathway", PATHWAYS))
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    pathway: Mapped[str] = mapped_column(String(16))
    task_code: Mapped[str | None] = mapped_column(String(16))
    observable_performance: Mapped[str] = mapped_column(Text)
    conditions: Mapped[str | None] = mapped_column(Text)
    acceptable_evidence: Mapped[str | None] = mapped_column(Text)
    reference_alignment: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(64))
    source_row: Mapped[dict[str, Any]]


class Module(CreatedAt, _VersionScoped, Base):
    __tablename__ = "modules"
    __table_args__ = (UniqueConstraint("course_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    sequence: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    teaching_mode: Mapped[str | None] = mapped_column(String(64))
    objectives_text: Mapped[str | None] = mapped_column(Text)
    instructional_content: Mapped[str | None] = mapped_column(Text)
    required_output: Mapped[str | None] = mapped_column(Text)
    source_row: Mapped[dict[str, Any]]

    lessons: Mapped[list[Lesson]] = relationship(back_populates="module", order_by="Lesson.sequence")


class Lesson(CreatedAt, Base):
    """Lesson content is authored separately from the workbook and carries its own approval status."""

    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("module_id", "code"), one_of("approval_status", APPROVAL_STATUSES))
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    sections: Mapped[list[Any]]
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    provenance_note: Mapped[str] = mapped_column(Text)
    content_version: Mapped[int] = mapped_column(Integer, default=1)

    module: Mapped[Module] = relationship(back_populates="lessons")


class LessonProgress(CreatedAt, Base):
    """Records that a student reviewed a lesson. Never used as evidence of proficiency."""

    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("lesson_id", "user_id", "cohort_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))


class LessonRelease(CreatedAt, Base):
    """Cohort-specific instructional lifecycle controlled by staff."""

    __tablename__ = "lesson_releases"
    __table_args__ = (
        UniqueConstraint("lesson_id", "cohort_id"),
        one_of("state", ("scheduled", "taught", "released", "withdrawn")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    released_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(16), default="released")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taught_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurriculumDocument(CreatedAt, _VersionScoped, Base):
    """Integrity-controlled metadata for a source document; bytes are never exposed by this model."""

    __tablename__ = "curriculum_documents"
    __table_args__ = (
        UniqueConstraint(
            "course_version_id", "document_code", "version_number", name="uq_curriculum_document_version"
        ),
        UniqueConstraint("course_version_id", "source_sha256", name="uq_curriculum_document_hash"),
        one_of("approval_status", APPROVAL_STATUSES),
        Index("ix_curriculum_documents_audience_release_day", "audience", "release_day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    replaces_document_id: Mapped[int | None] = mapped_column(ForeignKey("curriculum_documents.id"))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    document_code: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    media_type: Mapped[str] = mapped_column(String(128))
    source_filename: Mapped[str] = mapped_column(String(256))
    source_locator: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(String(512))
    source_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    slide_count: Mapped[int | None] = mapped_column(Integer)
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    scan_status: Mapped[str] = mapped_column(String(24), default="pending")
    scan_engine: Mapped[str | None] = mapped_column(String(64))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    audience: Mapped[str | None] = mapped_column(String(32))
    release_day: Mapped[str | None] = mapped_column(String(16))
    release_block: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)


class CurriculumDocumentRelease(CreatedAt, Base):
    """Cohort-scoped document visibility created by a lesson lifecycle transition."""

    __tablename__ = "curriculum_document_releases"
    __table_args__ = (
        UniqueConstraint("cohort_id", "document_id"),
        Index("ix_curriculum_document_releases_visibility", "cohort_id", "state"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    document_id: Mapped[int] = mapped_column(ForeignKey("curriculum_documents.id", ondelete="CASCADE"))
    released_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # NULL when released by the release plan directly (manual/scheduled) rather than by a lesson stage.
    trigger_lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(16), default="released")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Copied from the releasing plan item: only squads holding this track see the document. NULL = everyone.
    track: Mapped[str | None] = mapped_column(String(16))


class ScheduleBlock(CreatedAt, _VersionScoped, Base):
    __tablename__ = "schedule_blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    day: Mapped[str] = mapped_column(String(8))
    day_index: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    block_type: Mapped[str] = mapped_column(String(32))
    ref_code: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    format: Mapped[str | None] = mapped_column(String(64))
    audience: Mapped[str | None] = mapped_column(String(64))
    objectives_text: Mapped[str | None] = mapped_column(Text)
    scored_text: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)


class Exercise(CreatedAt, _VersionScoped, Base):
    __tablename__ = "exercises"
    __table_args__ = (UniqueConstraint("course_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(256))
    format: Mapped[str | None] = mapped_column(String(64))
    audience: Mapped[str | None] = mapped_column(String(64))
    day: Mapped[str | None] = mapped_column(String(8))
    source_block_type: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)


class AssessmentInstrument(CreatedAt, _VersionScoped, Base):
    __tablename__ = "assessment_instruments"
    __table_args__ = (UniqueConstraint("course_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str | None] = mapped_column(String(32))
    day: Mapped[str | None] = mapped_column(String(8))
    student_evidence: Mapped[str | None] = mapped_column(Text)
    scoring_method: Mapped[str | None] = mapped_column(Text)
    approval_standard: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)
    # Separate from content approval: whether the instrument is authorized for scored use.
    authorization_status: Mapped[str] = mapped_column(String(32), default="not_authorized")


class CurriculumLink(CreatedAt, _VersionScoped, Base):
    """One relationship exactly as stated by one source sheet."""

    __tablename__ = "curriculum_links"
    __table_args__ = (
        UniqueConstraint("course_version_id", "source_sheet", "link_type", "from_code", "to_code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_sheet: Mapped[str] = mapped_column(String(64))
    link_type: Mapped[str] = mapped_column(String(48))
    from_code: Mapped[str] = mapped_column(String(16))
    to_code: Mapped[str] = mapped_column(String(16))
    source_row_ref: Mapped[str | None] = mapped_column(String(32))
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict)


class QAGate(CreatedAt, _VersionScoped, Base):
    __tablename__ = "qa_gates"
    __table_args__ = (UniqueConstraint("course_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    fleta_ref: Mapped[str | None] = mapped_column(String(32))
    control_area: Mapped[str] = mapped_column(String(128))
    required_work: Mapped[str | None] = mapped_column(Text)
    accountable_role: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    evidence_artifact: Mapped[str | None] = mapped_column(Text)


class ActionItem(CreatedAt, _VersionScoped, Base):
    """Action Register rows (B01-B12) from the source workbook."""

    __tablename__ = "action_items"
    __table_args__ = (UniqueConstraint("course_version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    priority: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(128))
    gate: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32))


class RubricCriterion(CreatedAt, Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (
        UniqueConstraint("instrument_id", "code"),
        one_of("pathway", PATHWAYS),
        one_of("approval_status", APPROVAL_STATUSES),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("assessment_instruments.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(24))
    sequence: Mapped[int] = mapped_column(Integer)
    pathway: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    source_note: Mapped[str] = mapped_column(Text)


class CompetencyRule(CreatedAt, Base):
    """Approved standard of competence for an objective (FLETA 3.12 / QA gate Q12).

    Intentionally unpopulated: no rule exists until SMEs complete documented standard setting.
    """

    __tablename__ = "competency_rules"
    __table_args__ = (one_of("approval_status", APPROVAL_STATUSES),)
    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("objectives.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRun(CreatedAt, Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(256))
    source_sha256: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    course_version_id: Mapped[int | None] = mapped_column(ForeignKey("course_versions.id"))
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)

    issues: Mapped[list[ImportIssue]] = relationship(back_populates="run", order_by="ImportIssue.id")


class ImportIssue(CreatedAt, Base):
    __tablename__ = "import_issues"
    __table_args__ = (one_of("severity", ("info", "warning", "conflict", "error")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    import_run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict[str, Any]] = mapped_column(default=dict)
    resolution_status: Mapped[str] = mapped_column(String(32), default="unresolved")

    run: Mapped[ImportRun] = relationship(back_populates="issues")
