"""Assignments, drafts, immutable submissions, evaluations and handoffs.

``submissions``, ``evaluation_records``, ``criterion_results``, ``objective_evidence_notes`` and
``feedback_releases`` are append-only. The initial migration installs triggers that reject UPDATE and
DELETE on these tables, so immutability does not depend on application code alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import APPROVAL_STATUSES, STUDENT_PATHWAYS, Base, CreatedAt, one_of, utcnow

OBSERVATIONS = ("observed", "partially_observed", "not_observed", "not_assessed")


class AssignmentTemplate(CreatedAt, Base):
    __tablename__ = "assignment_templates"
    __table_args__ = (
        UniqueConstraint("code"),
        one_of("pathway", STUDENT_PATHWAYS),
        one_of("approval_status", APPROVAL_STATUSES),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("assessment_instruments.id"))
    pathway: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    product_name: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)
    sections: Mapped[list[Any]]
    approval_status: Mapped[str] = mapped_column(String(16), default="draft")
    content_version: Mapped[int] = mapped_column(Integer, default=1)


class Assignment(CreatedAt, Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("cohort_id", "template_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("assignment_templates.id"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")

    template: Mapped[AssignmentTemplate] = relationship()


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cited_evidence: Mapped[list[Any]] = mapped_column(default=list)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", "attempt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="RESTRICT"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="RESTRICT"))
    pathway: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    template_code: Mapped[str] = mapped_column(String(32))
    template_version: Mapped[int] = mapped_column(Integer)
    template_snapshot: Mapped[list[Any]]
    content: Mapped[dict[str, Any]]
    cited_evidence: Mapped[list[Any]]
    content_sha256: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignment: Mapped[Assignment] = relationship()
    student: Mapped[Any] = relationship("User")


class EvaluationRecord(Base):
    """One saved revision of provisional evaluator feedback. Never edited; new revisions append."""

    __tablename__ = "evaluation_records"
    __table_args__ = (
        UniqueConstraint("submission_id", "revision"),
        one_of("status", ("provisional",)),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="RESTRICT"))
    evaluator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer)
    # Only "provisional" is permitted until approved rubrics and competence standards exist.
    status: Mapped[str] = mapped_column(String(16), default="provisional")
    summary_comment: Mapped[str] = mapped_column(Text, default="")
    remediation_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    evaluator: Mapped[Any] = relationship("User")
    criterion_results: Mapped[list[CriterionResult]] = relationship(order_by="CriterionResult.id")
    objective_notes: Mapped[list[ObjectiveEvidenceNote]] = relationship(order_by="ObjectiveEvidenceNote.id")


class CriterionResult(Base):
    __tablename__ = "criterion_results"
    __table_args__ = (
        UniqueConstraint("evaluation_record_id", "criterion_id"),
        one_of("observation", OBSERVATIONS),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_record_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_records.id", ondelete="RESTRICT")
    )
    criterion_id: Mapped[int] = mapped_column(ForeignKey("rubric_criteria.id"))
    observation: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list[Any]] = mapped_column(default=list)


class ObjectiveEvidenceNote(Base):
    """Evaluator's note on how this artifact bears on an objective. Not a determination."""

    __tablename__ = "objective_evidence_notes"
    __table_args__ = (UniqueConstraint("evaluation_record_id", "objective_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_record_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_records.id", ondelete="RESTRICT")
    )
    objective_id: Mapped[int] = mapped_column(ForeignKey("objectives.id"))
    note: Mapped[str] = mapped_column(Text)


class FeedbackRelease(Base):
    __tablename__ = "feedback_releases"
    __table_args__ = (UniqueConstraint("evaluation_record_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_record_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_records.id", ondelete="RESTRICT")
    )
    released_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ObjectiveDetermination(CreatedAt, Base):
    """Final competency determination. Requires an approved CompetencyRule (none exist yet)."""

    __tablename__ = "objective_determinations"
    __table_args__ = (one_of("determination", ("proficient", "not_yet_proficient")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    objective_id: Mapped[int] = mapped_column(ForeignKey("objectives.id"))
    rule_id: Mapped[int] = mapped_column(ForeignKey("competency_rules.id"))
    determination: Mapped[str] = mapped_column(String(24))
    determined_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Handoff(CreatedAt, Base):
    """Investigator-analyst handoff record within a squad (J01 practice)."""

    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    squad_id: Mapped[int] = mapped_column(ForeignKey("squads.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    established: Mapped[str] = mapped_column(Text, default="")
    assessed: Mapped[str] = mapped_column(Text, default="")
    unknown: Mapped[str] = mapped_column(Text, default="")
    next_action_owner: Mapped[str] = mapped_column(Text, default="")
    cited_evidence: Mapped[list[Any]] = mapped_column(default=list)

    author: Mapped[Any] = relationship("User", foreign_keys=[author_id])
    recipient: Mapped[Any] = relationship("User", foreign_keys=[recipient_id])
