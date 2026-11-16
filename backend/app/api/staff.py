"""Instructor and evaluator portal: cohort console, submission review, provisional feedback."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api.cases import _staff_preview
from app.api.curriculum import schedule_out
from app.api.student import cohort_summary, squad_out, student_squad
from app.db import get_db
from app.models import (
    Cohort,
    CohortMembership,
    CurriculumDocument,
    EvaluationRecord,
    FeedbackRelease,
    Lesson,
    LessonRelease,
    Module,
    ScheduleBlock,
    Squad,
    Submission,
    User,
)
from app.schemas.common import (
    BulkFeedbackReleaseIn,
    BulkFeedbackReleaseOut,
    BulkLessonReleaseIn,
    CohortConsoleOut,
    CohortSummaryOut,
    CriterionOut,
    CurriculumDocumentOut,
    EvaluationIn,
    EvaluationRecordOut,
    GradingQueueItemOut,
    LessonReleaseIn,
    LessonReleaseOut,
    ObjectiveOut,
    ReviewOut,
    RosterAssignmentStatus,
    RosterEntryOut,
)
from app.security.authz import (
    STAFF_ROLES,
    Principal,
    deny,
    get_principal,
    require_cohort_role,
    require_csrf_header,
)
from app.services import evaluation as ev
from app.services import work
from app.services.lesson_delivery import open_due_releases
from app.services.visibility import active_cohort_case

router = APIRouter(prefix="/api/staff", tags=["staff"])


def _release_authority(db: Session, principal: Principal, cohort_id: int) -> None:
    if "instructor" in principal.cohort_roles(cohort_id) or "program_admin" in principal.global_roles:
        return
    raise deny(
        db,
        principal,
        action="lesson.release.manage",
        entity_type="cohort",
        entity_id=cohort_id,
        cohort_id=cohort_id,
        code=status.HTTP_403_FORBIDDEN,
    )


@router.get("/cohorts/{cohort_id}/lesson-releases", response_model=list[LessonReleaseOut])
def lesson_releases(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    _release_authority(db, principal, cohort_id)
    cohort = db.get(Cohort, cohort_id)
    if cohort is None:
        raise deny(db, principal, action="lesson.release.list", entity_type="cohort", entity_id=cohort_id)
    open_due_releases(db, cohort_id)
    releases = {
        r.lesson_id: r for r in db.scalars(select(LessonRelease).where(LessonRelease.cohort_id == cohort_id))
    }
    lessons = db.execute(
        select(Lesson, Module)
        .join(Module)
        .where(Module.course_version_id == cohort.course_version_id)
        .order_by(Module.sequence, Lesson.sequence)
    ).all()
    return [
        LessonReleaseOut(
            lesson_id=lesson.id,
            lesson_code=lesson.code,
            module_code=module.code,
            title=lesson.title,
            approval_status=lesson.approval_status,
            lifecycle_state=releases[lesson.id].state if lesson.id in releases else "locked",
            released=lesson.id in releases and releases[lesson.id].state == "released",
            released_at=releases[lesson.id].released_at if lesson.id in releases else None,
            taught_at=releases[lesson.id].taught_at if lesson.id in releases else None,
            scheduled_for=releases[lesson.id].scheduled_for if lesson.id in releases else None,
            withdrawn_at=releases[lesson.id].withdrawn_at if lesson.id in releases else None,
        )
        for lesson, module in lessons
    ]


@router.post(
    "/cohorts/{cohort_id}/lesson-releases/{lesson_id}",
    response_model=LessonReleaseOut,
    dependencies=[Depends(require_csrf_header)],
)
def release_lesson(
    cohort_id: int,
    lesson_id: int,
    body: LessonReleaseIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _release_authority(db, principal, cohort_id)
    lesson = db.get(Lesson, lesson_id)
    module = db.get(Module, lesson.module_id) if lesson else None
    cohort = db.get(Cohort, cohort_id)
    if (
        lesson is None
        or module is None
        or cohort is None
        or module.course_version_id != cohort.course_version_id
    ):
        raise deny(
            db,
            principal,
            action="lesson.release",
            entity_type="lesson",
            entity_id=lesson_id,
            cohort_id=cohort_id,
        )
    release = db.scalar(
        select(LessonRelease).where(
            LessonRelease.cohort_id == cohort_id, LessonRelease.lesson_id == lesson_id
        )
    )
    if body.lifecycle_state == "scheduled" and body.scheduled_for is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "scheduled_for is required")
    now = datetime.now(UTC)
    if release is None:
        release = LessonRelease(cohort_id=cohort_id, lesson_id=lesson_id, released_by_id=principal.id)
        db.add(release)
    release.state = body.lifecycle_state
    release.released_by_id = principal.id
    release.scheduled_for = body.scheduled_for if body.lifecycle_state == "scheduled" else None
    release.taught_at = body.taught_at or (now if body.lifecycle_state == "taught" else release.taught_at)
    release.released_at = now if body.lifecycle_state == "released" else None
    release.withdrawn_at = now if body.lifecycle_state == "withdrawn" else None
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action=f"lesson.{body.lifecycle_state}",
        entity_type="lesson",
        entity_id=lesson_id,
        cohort_id=cohort_id,
        details={
            "lesson_code": lesson.code,
            "scheduled_for": body.scheduled_for.isoformat() if body.scheduled_for else None,
        },
    )
    db.commit()
    return LessonReleaseOut(
        lesson_id=lesson.id,
        lesson_code=lesson.code,
        module_code=module.code,
        title=lesson.title,
        approval_status=lesson.approval_status,
        lifecycle_state=release.state,
        released=release.state == "released",
        released_at=release.released_at,
        taught_at=release.taught_at,
        scheduled_for=release.scheduled_for,
        withdrawn_at=release.withdrawn_at,
    )


@router.delete(
    "/cohorts/{cohort_id}/lesson-releases/{lesson_id}",
    status_code=204,
    dependencies=[Depends(require_csrf_header)],
)
def lock_lesson(
    cohort_id: int,
    lesson_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _release_authority(db, principal, cohort_id)
    release = db.scalar(
        select(LessonRelease).where(
            LessonRelease.cohort_id == cohort_id, LessonRelease.lesson_id == lesson_id
        )
    )
    if release is not None:
        db.delete(release)
        audit.record(
            db,
            actor_id=principal.id,
            action="lesson.lock",
            entity_type="lesson",
            entity_id=lesson_id,
            cohort_id=cohort_id,
        )
        db.commit()


@router.post(
    "/cohorts/{cohort_id}/lesson-release-bulk",
    response_model=list[LessonReleaseOut],
    dependencies=[Depends(require_csrf_header)],
)
def bulk_lesson_release(
    cohort_id: int,
    body: BulkLessonReleaseIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _release_authority(db, principal, cohort_id)
    if bool(body.module_code) == bool(body.teaching_block):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide one module_code or teaching_block"
        )
    cohort = db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cohort not found")
    module_codes = (
        [body.module_code]
        if body.module_code
        else list(
            db.scalars(
                select(ScheduleBlock.ref_code)
                .where(
                    ScheduleBlock.course_version_id == cohort.course_version_id,
                    ScheduleBlock.day == body.teaching_block,
                    ScheduleBlock.ref_code.like("M%"),
                )
                .distinct()
            )
        )
    )
    lessons = list(
        db.scalars(
            select(Lesson)
            .join(Module)
            .where(Module.course_version_id == cohort.course_version_id, Module.code.in_(module_codes))
        )
    )
    for lesson in lessons:
        release_lesson(
            cohort_id,
            lesson.id,
            LessonReleaseIn(
                lifecycle_state=body.lifecycle_state,
                scheduled_for=body.scheduled_for,
                taught_at=body.taught_at,
            ),
            principal,
            db,
        )
    return lesson_releases(cohort_id, principal, db)


@router.get("/curriculum-documents", response_model=list[CurriculumDocumentOut])
def curriculum_documents(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not ({"program_admin", "curriculum_editor", "content_approver"} & principal.global_roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Curriculum document access required")
    rows = db.execute(
        select(CurriculumDocument, Module)
        .outerjoin(Module, Module.id == CurriculumDocument.module_id)
        .order_by(CurriculumDocument.document_code)
    ).all()
    return [
        CurriculumDocumentOut(
            id=document.id,
            document_code=document.document_code,
            module_code=module.code if module else None,
            title=document.title,
            media_type=document.media_type,
            source_filename=document.source_filename,
            source_sha256=document.source_sha256,
            byte_size=document.byte_size,
            slide_count=document.slide_count,
            approval_status=document.approval_status,
            version_number=document.version_number,
            replaces_document_id=document.replaces_document_id,
            scan_status=document.scan_status,
            scan_engine=document.scan_engine,
            scanned_at=document.scanned_at,
            imported_at=document.created_at,
        )
        for document, module in rows
    ]


RUBRIC_NOTICE = (
    "PROVISIONAL. P02 criteria are development placeholders derived from proposed scoring dimensions. "
    "Observations recorded here are formative feedback, not approved competency determinations. "
    "No cut score, weighting or mastery rule is configured."
)


@router.get("/cohorts", response_model=list[CohortSummaryOut])
def my_cohorts(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[CohortSummaryOut]:
    if "program_admin" in principal.global_roles:
        return [cohort_summary(c, principal) for c in db.scalars(select(Cohort).order_by(Cohort.start_date))]
    ids = principal.staff_cohort_ids()
    if not ids:
        raise deny(
            db,
            principal,
            action="staff.cohorts",
            entity_type="staff_portal",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason="no staff role",
        )
    return [
        cohort_summary(c, principal)
        for c in db.scalars(select(Cohort).where(Cohort.id.in_(ids)).order_by(Cohort.start_date))
    ]


@router.get("/cohorts/{cohort_id}", response_model=CohortConsoleOut)
def cohort_console(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CohortConsoleOut:
    if "program_admin" not in principal.global_roles:
        require_cohort_role(db, principal, cohort_id, STAFF_ROLES, "cohort.console")
    cohort = db.get(Cohort, cohort_id)
    assert cohort is not None
    members = db.execute(
        select(CohortMembership, User)
        .join(User, User.id == CohortMembership.user_id)
        .where(CohortMembership.cohort_id == cohort_id)
        .order_by(CohortMembership.role, CohortMembership.pathway, User.display_name)
    ).all()
    templates_by_pathway = {
        p: work.student_assignments(db, cohort_id, p) for p in ("investigator", "analyst")
    }
    roster, staff = [], []
    for m, u in members:
        squad = student_squad(db, cohort_id, u.id) if m.role == "student" else None
        statuses = []
        for a, t in templates_by_pathway.get(m.pathway or "", []):
            st, sub = work.student_status(db, a.id, u.id)
            revisions = released = 0
            if sub is not None:
                revisions = (
                    db.scalar(
                        select(func.count())
                        .select_from(EvaluationRecord)
                        .where(EvaluationRecord.submission_id == sub.id)
                    )
                    or 0
                )
                released = (
                    db.scalar(
                        select(func.count())
                        .select_from(FeedbackRelease)
                        .join(EvaluationRecord, EvaluationRecord.id == FeedbackRelease.evaluation_record_id)
                        .where(EvaluationRecord.submission_id == sub.id)
                    )
                    or 0
                )
            statuses.append(
                RosterAssignmentStatus(
                    assignment_id=a.id,
                    template_code=t.code,
                    status=st,  # type: ignore[arg-type]
                    submission_id=sub.id if sub else None,
                    submitted_at=sub.submitted_at if sub else None,
                    evaluation_revisions=revisions,
                    feedback_released=released > 0,
                )
            )
        entry = RosterEntryOut(
            user_id=u.id,
            display_name=u.display_name,
            role=m.role,
            pathway=m.pathway,
            squad=squad.name if squad else None,
            assignments=statuses,
        )
        (roster if m.role == "student" else staff).append(entry)
    active = active_cohort_case(db, cohort_id)
    assignments = [
        work.summarize(db, a, t, cohort.course_version_id, None)
        for p in ("investigator", "analyst")
        for a, t in templates_by_pathway[p]
    ]
    return CohortConsoleOut(
        cohort=cohort_summary(cohort, principal),
        case_code=active[2].code if active else None,
        case_title=active[2].title if active else None,
        roster=roster,
        staff=staff,
        squads=[
            squad_out(db, s)
            for s in db.scalars(select(Squad).where(Squad.cohort_id == cohort_id).order_by(Squad.name))
        ],
        assignments=assignments,
        injects=_staff_preview(db, cohort_id).injects if active else [],
        schedule=schedule_out(db, cohort.course_version_id, cohort.start_date),
    )


@router.get("/cohorts/{cohort_id}/grading-queue", response_model=list[GradingQueueItemOut])
def grading_queue(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    if "program_admin" not in principal.global_roles:
        require_cohort_role(db, principal, cohort_id, STAFF_ROLES, "grading.queue")
    submissions = db.scalars(
        select(Submission).where(Submission.cohort_id == cohort_id).order_by(Submission.submitted_at)
    ).all()
    out = []
    for submission in submissions:
        latest = db.scalar(
            select(EvaluationRecord)
            .where(EvaluationRecord.submission_id == submission.id)
            .order_by(EvaluationRecord.revision.desc())
            .limit(1)
        )
        released = bool(
            latest
            and db.scalar(select(FeedbackRelease.id).where(FeedbackRelease.evaluation_record_id == latest.id))
        )
        out.append(
            GradingQueueItemOut(
                submission_id=submission.id,
                student_name=submission.student.display_name,
                template_code=submission.template_code,
                submitted_at=submission.submitted_at,
                latest_revision_id=latest.id if latest else None,
                rubric_complete=ev.rubric_complete(db, latest) if latest else False,
                feedback_released=released,
            )
        )
    return out


def _staff_submission(db: Session, principal: Principal, submission_id: int, action: str) -> Submission:
    sub = db.get(Submission, submission_id)
    is_admin = "program_admin" in principal.global_roles
    if sub is None or (not is_admin and not principal.cohort_roles(sub.cohort_id) & STAFF_ROLES):
        raise deny(
            db,
            principal,
            action=action,
            entity_type="submission",
            entity_id=submission_id,
            cohort_id=sub.cohort_id if sub else None,
            code=status.HTTP_403_FORBIDDEN
            if principal.student_memberships() and sub
            else status.HTTP_404_NOT_FOUND,
        )
    return sub


@router.get("/submissions/{submission_id}/review", response_model=ReviewOut)
def review(
    submission_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> ReviewOut:
    sub = _staff_submission(db, principal, submission_id, "submission.review")
    _a, template, cohort = ev.submission_context(db, sub)
    _ex, inst_code = work.assignment_codes(db, template)
    preview = {e.code: e for e in _staff_preview(db, cohort.id).evidence}
    return ReviewOut(
        submission=work.submission_out(db, sub),
        criteria=[CriterionOut.model_validate(c) for c in ev.criteria_for(db, template)],
        objectives_in_scope=[
            ObjectiveOut.model_validate(o) for o in ev.objectives_in_scope(db, cohort, template, inst_code)
        ],
        evaluations=ev.evaluation_history(db, sub.id),
        cited_evidence=[preview[c] for c in sub.cited_evidence if c in preview],
        rubric_notice=RUBRIC_NOTICE,
    )


@router.post(
    "/submissions/{submission_id}/evaluations",
    response_model=EvaluationRecordOut,
    dependencies=[Depends(require_csrf_header)],
)
def record_evaluation(
    submission_id: int,
    body: EvaluationIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationRecordOut:
    sub = _staff_submission(db, principal, submission_id, "evaluation.record")
    _a, template, _c = ev.submission_context(db, sub)
    _ex, inst_code = work.assignment_codes(db, template)
    record = ev.record_evaluation(db, principal, sub, body, inst_code)
    db.commit()
    return next(r for r in ev.evaluation_history(db, sub.id) if r.id == record.id)


@router.post(
    "/evaluations/{record_id}/release",
    response_model=EvaluationRecordOut,
    dependencies=[Depends(require_csrf_header)],
)
def release(
    record_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> EvaluationRecordOut:
    record = db.get(EvaluationRecord, record_id)
    sub = db.get(Submission, record.submission_id) if record else None
    is_admin = "program_admin" in principal.global_roles
    if (
        record is None
        or sub is None
        or (not is_admin and not principal.cohort_roles(sub.cohort_id) & STAFF_ROLES)
    ):
        raise deny(
            db,
            principal,
            action="feedback.release",
            entity_type="evaluation_record",
            entity_id=record_id,
            cohort_id=sub.cohort_id if sub else None,
        )
    ev.release_feedback(db, principal, record, sub.cohort_id)
    db.commit()
    return next(r for r in ev.evaluation_history(db, sub.id) if r.id == record.id)


@router.post(
    "/feedback/bulk-release",
    response_model=BulkFeedbackReleaseOut,
    dependencies=[Depends(require_csrf_header)],
)
def bulk_release_feedback(
    body: BulkFeedbackReleaseIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    ids = list(dict.fromkeys(body.evaluation_record_ids))
    records = list(db.scalars(select(EvaluationRecord).where(EvaluationRecord.id.in_(ids)).with_for_update()))
    if len(records) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more feedback revisions were not found")
    cohort_ids: set[int] = set()
    for record in records:
        sub = _staff_submission(db, principal, record.submission_id, "feedback.bulk_release")
        cohort_ids.add(sub.cohort_id)
        ev.release_feedback(db, principal, record, sub.cohort_id)
    summary = f"Released {len(records)} feedback revision(s) across {len(cohort_ids)} cohort(s)"
    audit.record(
        db,
        actor_id=principal.id,
        action="feedback.bulk_release",
        entity_type="evaluation_batch",
        entity_id=",".join(map(str, ids)),
        details={"record_ids": ids, "cohort_ids": sorted(cohort_ids), "summary": summary},
    )
    db.commit()
    return BulkFeedbackReleaseOut(
        released_count=len(records), evaluation_record_ids=ids, audit_summary=summary
    )
