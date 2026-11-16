"""Assignments, drafts and immutable submissions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models import (
    AssessmentInstrument,
    Assignment,
    AssignmentTemplate,
    CohortMembership,
    CurriculumLink,
    Draft,
    EvaluationRecord,
    Exercise,
    FeedbackRelease,
    ScheduleBlock,
    Submission,
    User,
)
from app.models.base import utcnow
from app.schemas.common import AssignmentSummaryOut, DraftIn, SubmissionOut
from app.security.authz import Principal, deny
from app.services.visibility import content_visible, released_evidence_codes

MAX_TEXT = 20_000
MAX_CELL = 4_000
MAX_ROWS = 60


# --- lookup ----------------------------------------------------------------------------------
def module_for_exercise(db: Session, course_version_id: int, exercise_code: str) -> str | None:
    """Module whose teaching block most recently precedes the exercise in the POI sequence (display only)."""
    blocks = db.scalars(
        select(ScheduleBlock)
        .where(ScheduleBlock.course_version_id == course_version_id)
        .order_by(ScheduleBlock.sequence)
    ).all()
    last_module: str | None = None
    for b in blocks:
        if b.ref_code and b.ref_code.startswith("M"):
            last_module = b.ref_code
        if b.ref_code == exercise_code:
            return last_module
    return None


def student_assignment(
    db: Session, principal: Principal, assignment_id: int, action: str
) -> tuple[Assignment, AssignmentTemplate, CohortMembership]:
    """Resolve an assignment for a student. Wrong cohort or wrong pathway -> 404 (audited)."""
    row = db.execute(
        select(Assignment, AssignmentTemplate)
        .join(AssignmentTemplate, AssignmentTemplate.id == Assignment.template_id)
        .where(Assignment.id == assignment_id)
    ).first()
    membership = principal.student_membership(row[0].cohort_id) if row else None
    if (
        row is None
        or membership is None
        or membership.pathway != row[1].pathway
        or not content_visible(row[1].approval_status)
    ):
        raise deny(
            db,
            principal,
            action=action,
            entity_type="assignment",
            entity_id=assignment_id,
            cohort_id=row[0].cohort_id if row else None,
            reason="not assigned to caller",
        )
    return row[0], row[1], membership


def assignment_codes(db: Session, template: AssignmentTemplate) -> tuple[str, str]:
    ex = db.get(Exercise, template.exercise_id)
    inst = db.get(AssessmentInstrument, template.instrument_id)
    assert ex is not None and inst is not None
    return ex.code, inst.code


def student_status(db: Session, assignment_id: int, student_id: int) -> tuple[str, Submission | None]:
    sub = db.scalar(
        select(Submission)
        .where(Submission.assignment_id == assignment_id, Submission.student_id == student_id)
        .order_by(Submission.attempt.desc())
        .limit(1)
    )
    if sub is not None:
        released = db.scalar(
            select(func.count())
            .select_from(FeedbackRelease)
            .join(EvaluationRecord, EvaluationRecord.id == FeedbackRelease.evaluation_record_id)
            .where(EvaluationRecord.submission_id == sub.id)
        )
        return ("feedback_available" if released else "submitted"), sub
    draft = db.scalar(
        select(Draft).where(Draft.assignment_id == assignment_id, Draft.student_id == student_id)
    )
    if draft is not None and draft.revision > 0:
        return "draft", None
    return "not_started", None


def summarize(
    db: Session,
    assignment: Assignment,
    template: AssignmentTemplate,
    course_version_id: int,
    student_id: int | None,
) -> AssignmentSummaryOut:
    ex_code, inst_code = assignment_codes(db, template)
    st, sub = student_status(db, assignment.id, student_id) if student_id else ("not_started", None)
    return AssignmentSummaryOut(
        id=assignment.id,
        cohort_id=assignment.cohort_id,
        template_code=template.code,
        title=template.title,
        product_name=template.product_name,
        pathway=template.pathway,
        exercise_code=ex_code,
        instrument_code=inst_code,
        module_code=module_for_exercise(db, course_version_id, ex_code),
        due_at=assignment.due_at,
        status=st,  # type: ignore[arg-type]
        submission_id=sub.id if sub else None,
    )


def student_assignments(
    db: Session, cohort_id: int, pathway: str
) -> list[tuple[Assignment, AssignmentTemplate]]:
    rows = db.execute(
        select(Assignment, AssignmentTemplate)
        .join(AssignmentTemplate, AssignmentTemplate.id == Assignment.template_id)
        .where(Assignment.cohort_id == cohort_id, AssignmentTemplate.pathway == pathway)
        .order_by(Assignment.due_at, Assignment.id)
    ).all()
    return [(a, t) for a, t in rows if content_visible(t.approval_status)]


# --- validation ------------------------------------------------------------------------------
def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


def validate_content(sections: list[dict[str, Any]], content: dict[str, Any]) -> dict[str, Any]:
    spec = {s["key"]: s for s in sections}
    unknown = set(content) - set(spec)
    if unknown:
        raise _bad(f"Unknown section(s): {sorted(unknown)}")
    cleaned: dict[str, Any] = {}
    for key, s in spec.items():
        value = content.get(key)
        if value is None:
            continue
        if s["kind"] == "text":
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise _bad(f"Section {key}: text up to {MAX_TEXT} characters required")
            cleaned[key] = value
        else:
            cols = {c["key"]: c for c in s["columns"]}
            if not isinstance(value, list) or len(value) > MAX_ROWS:
                raise _bad(f"Section {key}: list of up to {MAX_ROWS} rows required")
            rows = []
            for row in value:
                if not isinstance(row, dict) or set(row) - set(cols):
                    raise _bad(f"Section {key}: rows may only contain {sorted(cols)}")
                clean_row: dict[str, str] = {}
                for ck, cv in row.items():
                    if not isinstance(cv, str) or len(cv) > MAX_CELL:
                        raise _bad(f"Section {key}.{ck}: text up to {MAX_CELL} characters required")
                    opts = cols[ck].get("options")
                    if opts and cv and cv not in opts:
                        raise _bad(f"Section {key}.{ck}: must be one of {opts}")
                    clean_row[ck] = cv
                rows.append(clean_row)
            cleaned[key] = rows
    return cleaned


def _has_substance(content: dict[str, Any]) -> bool:
    for v in content.values():
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, list) and any(any(c.strip() for c in row.values()) for row in v):
            return True
    return False


def _check_citations(db: Session, cohort_id: int, cited: list[str]) -> list[str]:
    allowed = released_evidence_codes(db, cohort_id)
    ordered = list(dict.fromkeys(cited))
    if set(ordered) - allowed:
        # Same message for unreleased and nonexistent codes: does not confirm hidden evidence exists.
        raise _bad("Cited evidence must be released evidence identifiers for this case")
    return ordered


# --- drafts / submissions ---------------------------------------------------------------------
def get_or_create_draft(db: Session, assignment_id: int, student_id: int) -> Draft:
    draft = db.scalar(
        select(Draft).where(Draft.assignment_id == assignment_id, Draft.student_id == student_id)
    )
    if draft is None:
        draft = Draft(
            assignment_id=assignment_id, student_id=student_id, content={}, cited_evidence=[], revision=0
        )
        db.add(draft)
        db.flush()
    return draft


def save_draft(
    db: Session, principal: Principal, assignment: Assignment, template: AssignmentTemplate, payload: DraftIn
) -> Draft:
    if db.scalar(
        select(Submission.id).where(
            Submission.assignment_id == assignment.id, Submission.student_id == principal.id
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Already submitted; the submitted artifact is immutable"
        )
    content = validate_content(template.sections, payload.content)
    cited = _check_citations(db, assignment.cohort_id, payload.cited_evidence)
    draft = get_or_create_draft(db, assignment.id, principal.id)
    if payload.base_revision is not None and payload.base_revision != draft.revision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Draft changed elsewhere (server revision {draft.revision}); reload before saving",
        )
    draft.content = content
    draft.cited_evidence = cited
    draft.revision += 1
    draft.updated_at = utcnow()
    return draft


def canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def submit(
    db: Session,
    principal: Principal,
    assignment: Assignment,
    template: AssignmentTemplate,
    membership: CohortMembership,
) -> Submission:
    if db.scalar(
        select(Submission.id).where(
            Submission.assignment_id == assignment.id, Submission.student_id == principal.id
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already submitted")
    draft = db.scalar(
        select(Draft).where(Draft.assignment_id == assignment.id, Draft.student_id == principal.id)
    )
    if draft is None or not _has_substance(draft.content):
        raise _bad("Save a draft with content before submitting")
    content = validate_content(template.sections, draft.content)
    cited = _check_citations(db, assignment.cohort_id, draft.cited_evidence)
    if not cited:
        raise _bad("Cite at least one supporting evidence record before submitting")
    body = {
        "template_code": template.code,
        "template_version": template.content_version,
        "content": content,
        "cited_evidence": cited,
    }
    sub = Submission(
        assignment_id=assignment.id,
        student_id=principal.id,
        cohort_id=assignment.cohort_id,
        pathway=membership.pathway or "",
        attempt=1,
        template_code=template.code,
        template_version=template.content_version,
        template_snapshot=template.sections,
        content=content,
        cited_evidence=cited,
        content_sha256=canonical_hash(body),
        submitted_at=utcnow(),
    )
    db.add(sub)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="submission.create",
        entity_type="submission",
        entity_id=sub.id,
        cohort_id=assignment.cohort_id,
        details={"assignment_id": assignment.id, "template": template.code, "sha256": sub.content_sha256},
    )
    return sub


def submission_out(db: Session, sub: Submission) -> SubmissionOut:
    template = db.scalar(select(AssignmentTemplate).where(AssignmentTemplate.code == sub.template_code))
    student = db.get(User, sub.student_id)
    assert template is not None and student is not None
    return SubmissionOut(
        id=sub.id,
        assignment_id=sub.assignment_id,
        cohort_id=sub.cohort_id,
        student_id=sub.student_id,
        student_name=student.display_name,
        pathway=sub.pathway,
        attempt=sub.attempt,
        template_code=sub.template_code,
        template_version=sub.template_version,
        title=template.title,
        product_name=template.product_name,
        sections=sub.template_snapshot,
        content=sub.content,
        cited_evidence=list(sub.cited_evidence),
        content_sha256=sub.content_sha256,
        submitted_at=sub.submitted_at,
    )


def instrument_objective_codes(db: Session, course_version_id: int, instrument_code: str) -> list[str]:
    """Objectives an instrument evaluates, as stated on the Assessments sheet (the instrument blueprint)."""
    return list(
        db.scalars(
            select(CurriculumLink.to_code)
            .where(
                CurriculumLink.course_version_id == course_version_id,
                CurriculumLink.source_sheet == "Assessments",
                CurriculumLink.link_type == "instrument_objective",
                CurriculumLink.from_code == instrument_code,
            )
            .order_by(CurriculumLink.to_code)
        )
    )
