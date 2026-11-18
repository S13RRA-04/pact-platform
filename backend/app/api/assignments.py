"""Student assignment workspace: load, save draft, submit; and submission retrieval."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Case, Cohort, Draft, Submission
from app.schemas.common import AssignmentOut, DraftIn, DraftOut, SubmissionOut
from app.security.authz import STAFF_ROLES, Principal, deny, get_principal, require_csrf_header
from app.services import work
from app.services.visibility import released_evidence_codes, viewer_tracks

router = APIRouter(prefix="/api", tags=["assignments"])


def _assignment_out(db: Session, principal: Principal, assignment_id: int, action: str) -> AssignmentOut:
    assignment, template, _m = work.student_assignment(db, principal, assignment_id, action)
    cohort = db.get(Cohort, assignment.cohort_id)
    case = db.get(Case, assignment.case_id)
    assert cohort is not None and case is not None
    summary = work.summarize(db, assignment, template, cohort.course_version_id, principal.id)
    draft = db.scalar(
        select(Draft).where(Draft.assignment_id == assignment.id, Draft.student_id == principal.id)
    )
    return AssignmentOut(
        **summary.model_dump(),
        instructions=template.instructions,
        sections=template.sections,
        template_approval_status=template.approval_status,
        case_code=case.code,
        draft=DraftOut(
            content=draft.content if draft else {},
            cited_evidence=list(draft.cited_evidence) if draft else [],
            revision=draft.revision if draft else 0,
            updated_at=draft.updated_at if draft else None,
        ),
        available_evidence=sorted(
            released_evidence_codes(
                db, assignment.cohort_id, tracks=viewer_tracks(db, principal, assignment.cohort_id)
            )
        ),
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentOut)
def get_assignment(
    assignment_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> AssignmentOut:
    return _assignment_out(db, principal, assignment_id, "assignment.view")


@router.put(
    "/assignments/{assignment_id}/draft", response_model=DraftOut, dependencies=[Depends(require_csrf_header)]
)
def save_draft(
    assignment_id: int,
    body: DraftIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> DraftOut:
    assignment, template, _m = work.student_assignment(db, principal, assignment_id, "draft.save")
    draft = work.save_draft(db, principal, assignment, template, body)
    db.commit()
    return DraftOut(
        content=draft.content,
        cited_evidence=list(draft.cited_evidence),
        revision=draft.revision,
        updated_at=draft.updated_at,
    )


@router.post(
    "/assignments/{assignment_id}/submit",
    response_model=SubmissionOut,
    dependencies=[Depends(require_csrf_header)],
)
def submit(
    assignment_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> SubmissionOut:
    assignment, template, membership = work.student_assignment(
        db, principal, assignment_id, "submission.create"
    )
    sub = work.submit(db, principal, assignment, template, membership)
    db.commit()
    return work.submission_out(db, sub)


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> SubmissionOut:
    """Owner, or instructor/evaluator of the submission's cohort. Everyone else: 404 (audited)."""
    sub = db.get(Submission, submission_id)
    allowed = sub is not None and (
        sub.student_id == principal.id or bool(principal.cohort_roles(sub.cohort_id) & STAFF_ROLES)
    )
    if not allowed:
        raise deny(
            db,
            principal,
            action="submission.view",
            entity_type="submission",
            entity_id=submission_id,
            cohort_id=sub.cohort_id if sub else None,
        )
    assert sub is not None
    return work.submission_out(db, sub)
