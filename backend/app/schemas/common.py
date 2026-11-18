"""Explicit API response/request schemas.

Student-facing and staff-facing schemas are separate types. Instructor-only fields (answer keys,
instructor notes, unreleased status) exist only on ``Staff*`` schemas, so they cannot leak through
a student response by accident.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- identity ---------------------------------------------------------------------------------
class PersonaOut(Out):
    username: str
    display_name: str
    persona_label: str | None


class DevLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MembershipOut(Out):
    cohort_id: int
    cohort_code: str
    cohort_name: str
    role: str
    pathway: str | None


class MeOut(BaseModel):
    id: int
    username: str
    display_name: str
    persona_label: str | None
    global_roles: list[str]
    memberships: list[MembershipOut]
    environment: str
    synthetic_only: bool
    identity_provider: str


# --- curriculum -------------------------------------------------------------------------------
class ObjectiveOut(Out):
    code: str
    pathway: str
    task_code: str | None
    observable_performance: str
    conditions: str | None
    acceptable_evidence: str | None
    validation_status: str


class LinkOut(Out):
    source_sheet: str
    link_type: str
    from_code: str
    to_code: str


class LessonSummaryOut(Out):
    id: int
    code: str
    title: str
    duration_minutes: int | None
    approval_status: str


class LessonOut(LessonSummaryOut):
    sections: list[Any]
    provenance_note: str
    content_version: int
    reviewed: bool = False


class LessonReleaseOut(BaseModel):
    lesson_id: int
    lesson_code: str
    module_code: str
    title: str
    approval_status: str
    lifecycle_state: Literal["locked", "scheduled", "taught", "released", "withdrawn"]
    released: bool
    released_at: datetime | None
    taught_at: datetime | None
    scheduled_for: datetime | None
    withdrawn_at: datetime | None


class LessonReleaseIn(BaseModel):
    lifecycle_state: Literal["scheduled", "taught", "released", "withdrawn"] = "released"
    scheduled_for: datetime | None = None
    taught_at: datetime | None = None


class BulkLessonReleaseIn(LessonReleaseIn):
    module_code: str | None = Field(default=None, max_length=8)
    teaching_block: str | None = Field(default=None, max_length=16)


class CurriculumDocumentOut(BaseModel):
    id: int
    document_code: str
    module_code: str | None
    title: str
    media_type: str
    source_filename: str
    source_sha256: str
    byte_size: int
    slide_count: int | None
    approval_status: str
    version_number: int
    replaces_document_id: int | None
    scan_status: str
    scan_engine: str | None
    scanned_at: datetime | None
    audience: str | None
    release_day: str | None
    release_block: str | None
    imported_at: datetime


class StudentCourseDocumentOut(BaseModel):
    id: int
    document_code: str
    title: str
    media_type: str
    release_day: str
    release_block: str
    released_at: datetime


class GradingQueueItemOut(BaseModel):
    submission_id: int
    student_name: str
    template_code: str
    submitted_at: datetime
    latest_revision_id: int | None
    rubric_complete: bool
    feedback_released: bool


class BulkFeedbackReleaseIn(BaseModel):
    evaluation_record_ids: list[int] = Field(min_length=1, max_length=100)
    confirmation: Literal["RELEASE FEEDBACK"]


class BulkFeedbackReleaseOut(BaseModel):
    released_count: int
    evaluation_record_ids: list[int]
    audit_summary: str


class NotificationOut(BaseModel):
    id: int
    category: str
    title: str
    body: str
    entity_type: str | None
    entity_id: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationPreferenceOut(BaseModel):
    in_app_enabled: bool
    content_release_enabled: bool
    feedback_enabled: bool
    digest_frequency: Literal["immediate", "daily", "weekly", "off"]


class NotificationPreferenceIn(NotificationPreferenceOut):
    pass


class NotificationDigestOut(BaseModel):
    id: int
    frequency: str
    subject: str
    body: str
    delivered_at: datetime | None


class ModuleSummaryOut(Out):
    code: str
    sequence: int
    title: str
    teaching_mode: str | None
    required_output: str | None
    objective_codes: list[str]
    lesson_count: int
    schedule: list[str]


class ExerciseOut(Out):
    code: str
    title: str
    format: str | None
    audience: str | None
    day: str | None
    note: str | None


class InstrumentOut(Out):
    code: str
    name: str
    mode: str | None
    day: str | None
    student_evidence: str | None
    scoring_method: str | None
    approval_standard: str | None
    authorization_status: str


class ModuleDetailOut(BaseModel):
    code: str
    title: str
    teaching_mode: str | None
    instructional_content: str | None
    required_output: str | None
    objectives: list[ObjectiveOut]
    objective_links_by_sheet: dict[str, list[str]]
    lessons: list[LessonOut]
    exercises: list[ExerciseOut]
    instruments: list[InstrumentOut]
    schedule: list[ScheduleBlockOut]
    course_version: str
    course_version_status: str


class ScheduleBlockOut(Out):
    day: str
    day_index: int
    date: Date | None = None
    start_time: str
    end_time: str
    block_type: str
    ref_code: str | None
    title: str
    format: str | None
    audience: str | None
    objectives_text: str | None
    scored_text: str | None


ModuleDetailOut.model_rebuild()


# --- case / evidence --------------------------------------------------------------------------
class EvidenceOut(Out):
    code: str
    title: str
    source_type: str
    observed_at: datetime | None
    observed_timezone: str | None
    observed_as_recorded: str
    provenance: str
    limitations: str
    content: str
    release: str  # "baseline" or the inject code
    released_at: datetime | None


class StaffEvidenceOut(EvidenceOut):
    instructor_notes: str
    released: bool
    inject_approval_status: str | None
    track: str | None = None  # squad track the record is released on (None = every student)


class InjectBriefOut(BaseModel):
    code: str
    title: str
    student_briefing: str
    released_at: datetime


class CaseOut(BaseModel):
    cohort_id: int
    code: str
    title: str
    summary: str
    victim_organization: str
    fictional_disclaimer: str
    scenario_version: str
    activated_at: datetime
    evidence_count: int
    updates: list[InjectBriefOut]
    timeline: list[TimelineEntryOut]


class TimelineEntryOut(BaseModel):
    observed_at: datetime
    evidence_code: str
    title: str
    source_type: str
    observed_as_recorded: str


CaseOut.model_rebuild()


class StaffInjectOut(BaseModel):
    id: int
    code: str
    title: str
    student_briefing: str
    instructor_notes: str
    approval_status: str
    released: bool
    released_at: datetime | None
    released_by: str | None
    evidence_codes: list[str]
    track: str | None = None


class StaffEvidencePreviewOut(BaseModel):
    cohort_id: int
    case_code: str
    case_title: str
    instructor_overview: str
    scenario_version: str
    evidence: list[StaffEvidenceOut]
    injects: list[StaffInjectOut]


class ReleaseIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


# --- assignments ------------------------------------------------------------------------------
AssignmentStatus = Literal["not_started", "draft", "submitted", "feedback_available"]


class AssignmentSummaryOut(BaseModel):
    id: int
    cohort_id: int
    template_code: str
    title: str
    product_name: str
    pathway: str
    exercise_code: str
    instrument_code: str
    module_code: str | None
    due_at: datetime
    status: AssignmentStatus
    submission_id: int | None


class DraftOut(BaseModel):
    content: dict[str, Any]
    cited_evidence: list[str]
    revision: int
    updated_at: datetime | None


class DraftIn(BaseModel):
    content: dict[str, Any]
    cited_evidence: list[str] = Field(default_factory=list, max_length=100)
    base_revision: int | None = None


class AssignmentOut(AssignmentSummaryOut):
    instructions: str
    sections: list[Any]
    template_approval_status: str
    case_code: str
    draft: DraftOut
    available_evidence: list[str]


class SubmissionOut(BaseModel):
    id: int
    assignment_id: int
    cohort_id: int
    student_id: int
    student_name: str
    pathway: str
    attempt: int
    template_code: str
    template_version: int
    title: str
    product_name: str
    sections: list[Any]
    content: dict[str, Any]
    cited_evidence: list[str]
    content_sha256: str
    submitted_at: datetime


# --- evaluation -------------------------------------------------------------------------------
Observation = Literal["observed", "partially_observed", "not_observed", "not_assessed"]


class CriterionOut(Out):
    id: int
    code: str
    title: str
    description: str
    pathway: str
    approval_status: str
    source_note: str


class CriterionResultIn(BaseModel):
    criterion_id: int
    observation: Observation
    comment: str = Field(default="", max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)


class ObjectiveNoteIn(BaseModel):
    objective_code: str = Field(max_length=8)
    note: str = Field(min_length=1, max_length=4000)


class EvaluationIn(BaseModel):
    summary_comment: str = Field(default="", max_length=8000)
    remediation_note: str = Field(default="", max_length=4000)
    criterion_results: list[CriterionResultIn] = Field(default_factory=list, max_length=50)
    objective_notes: list[ObjectiveNoteIn] = Field(default_factory=list, max_length=20)


class CriterionResultOut(BaseModel):
    criterion_id: int
    criterion_code: str
    criterion_title: str
    observation: str
    comment: str
    evidence_refs: list[str]


class ObjectiveNoteOut(BaseModel):
    objective_code: str
    note: str


class EvaluationRecordOut(BaseModel):
    id: int
    revision: int
    status: str
    evaluator_name: str
    created_at: datetime
    summary_comment: str
    remediation_note: str
    criterion_results: list[CriterionResultOut]
    objective_notes: list[ObjectiveNoteOut]
    released: bool
    released_at: datetime | None


class ObjectiveStatusOut(BaseModel):
    objective_code: str
    pathway: str
    observable_performance: str
    evidence_notes: list[str]
    determination: Literal["not_determined"]
    determination_reason: str


class ReviewOut(BaseModel):
    submission: SubmissionOut
    criteria: list[CriterionOut]
    objectives_in_scope: list[ObjectiveOut]
    evaluations: list[EvaluationRecordOut]
    cited_evidence: list[StaffEvidenceOut]
    rubric_notice: str


class StudentAssessmentOut(BaseModel):
    submission: SubmissionOut
    feedback: EvaluationRecordOut | None
    objectives: list[ObjectiveStatusOut]


# --- cohort console -------------------------------------------------------------------------
class RosterAssignmentStatus(BaseModel):
    assignment_id: int
    template_code: str
    status: AssignmentStatus
    submission_id: int | None
    submitted_at: datetime | None
    evaluation_revisions: int
    feedback_released: bool


class RosterEntryOut(BaseModel):
    user_id: int
    display_name: str
    role: str
    pathway: str | None
    squad: str | None
    assignments: list[RosterAssignmentStatus]


class SquadOut(BaseModel):
    id: int
    name: str
    members: list[SquadMemberOut]
    case_track: str | None = None
    site_team: str | None = None


class SquadMemberOut(BaseModel):
    user_id: int
    display_name: str
    pathway: str | None


SquadOut.model_rebuild()


class CohortSummaryOut(BaseModel):
    id: int
    code: str
    name: str
    start_date: Date
    end_date: Date
    timezone: str
    my_roles: list[str]


class CohortConsoleOut(BaseModel):
    cohort: CohortSummaryOut
    case_code: str | None
    case_title: str | None
    roster: list[RosterEntryOut]
    staff: list[RosterEntryOut]
    squads: list[SquadOut]
    assignments: list[AssignmentSummaryOut]
    injects: list[StaffInjectOut]
    schedule: list[ScheduleBlockOut]


# --- student dashboard -----------------------------------------------------------------------
class EnrollmentOut(BaseModel):
    cohort: CohortSummaryOut
    pathway: str
    squad: SquadOut | None


class DashboardOut(BaseModel):
    display_name: str
    enrollments: list[EnrollmentOut]
    current_module: ModuleSummaryOut | None
    assignments: list[AssignmentSummaryOut]
    schedule: list[ScheduleBlockOut]
    lessons_reviewed: int
    lessons_available: int
    submissions: int
    feedback_released: int
    progress_notice: str


# --- squad / handoff ------------------------------------------------------------------------
class HandoffIn(BaseModel):
    recipient_id: int | None = None
    established: str = Field(default="", max_length=6000)
    assessed: str = Field(default="", max_length=6000)
    unknown: str = Field(default="", max_length=6000)
    next_action_owner: str = Field(default="", max_length=3000)
    cited_evidence: list[str] = Field(default_factory=list, max_length=50)


class HandoffOut(BaseModel):
    id: int
    author_name: str
    author_pathway: str | None
    recipient_name: str | None
    established: str
    assessed: str
    unknown: str
    next_action_owner: str
    cited_evidence: list[str]
    created_at: datetime


class SquadViewOut(BaseModel):
    cohort_id: int
    squad: SquadOut
    handoffs: list[HandoffOut]


# --- admin -------------------------------------------------------------------------------------
class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor: str | None
    action: str
    outcome: str
    entity_type: str | None
    entity_id: str | None
    cohort_id: int | None
    details: dict[str, Any]


class ApprovalOut(BaseModel):
    id: int
    workflow: str
    entity_type: str
    entity_code: str
    summary: str
    status: str
    requested_by: str
    requested_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)
