"""Student dashboard, assessment center and squad collaboration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api.curriculum import module_summaries, schedule_out
from app.db import get_db
from app.models import (
    Cohort,
    CohortMembership,
    EvaluationRecord,
    FeedbackRelease,
    Handoff,
    Lesson,
    LessonProgress,
    Module,
    Notification,
    NotificationDigest,
    NotificationPreference,
    Squad,
    SquadMember,
    Submission,
    User,
)
from app.models.base import utcnow
from app.schemas.common import (
    CohortSummaryOut,
    DashboardOut,
    EnrollmentOut,
    HandoffIn,
    HandoffOut,
    NotificationDigestOut,
    NotificationOut,
    NotificationPreferenceIn,
    NotificationPreferenceOut,
    SquadMemberOut,
    SquadOut,
    SquadViewOut,
    StudentAssessmentOut,
)
from app.security.authz import Principal, deny, get_principal, require_csrf_header
from app.services import evaluation as ev
from app.services import work
from app.services.visibility import active_cohort_case, content_visible, released_evidence_codes

router = APIRouter(prefix="/api/student", tags=["student"])


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == principal.id)
            .order_by(Notification.id.desc())
            .limit(100)
        )
    )


@router.get("/notification-digests", response_model=list[NotificationDigestOut])
def notification_digests(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(NotificationDigest)
            .where(NotificationDigest.user_id == principal.id, NotificationDigest.status == "delivered")
            .order_by(NotificationDigest.id.desc())
            .limit(50)
        )
    )


@router.post(
    "/notifications/{notification_id}/read", status_code=204, dependencies=[Depends(require_csrf_header)]
)
def mark_notification_read(
    notification_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != principal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    item.read_at = utcnow()
    db.commit()


@router.delete(
    "/notifications/{notification_id}/read", status_code=204, dependencies=[Depends(require_csrf_header)]
)
def mark_notification_unread(
    notification_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != principal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    item.read_at = None
    db.commit()


@router.get("/notification-preferences", response_model=NotificationPreferenceOut)
def notification_preferences(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    pref = db.get(NotificationPreference, principal.id)
    return (
        NotificationPreferenceOut.model_validate(pref, from_attributes=True)
        if pref
        else NotificationPreferenceOut(
            in_app_enabled=True,
            content_release_enabled=True,
            feedback_enabled=True,
            digest_frequency="immediate",
        )
    )


@router.put(
    "/notification-preferences",
    response_model=NotificationPreferenceOut,
    dependencies=[Depends(require_csrf_header)],
)
def update_notification_preferences(
    body: NotificationPreferenceIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    pref = db.get(NotificationPreference, principal.id) or NotificationPreference(user_id=principal.id)
    for key, value in body.model_dump().items():
        setattr(pref, key, value)
    pref.updated_at = utcnow()
    db.add(pref)
    db.commit()
    return NotificationPreferenceOut.model_validate(pref, from_attributes=True)


PROGRESS_NOTICE = (
    "Progress shows activity only. Lesson review, attendance and submission counts are not evidence of "
    "proficiency; objective determinations require approved competence standards."
)


def cohort_summary(cohort: Cohort, principal: Principal) -> CohortSummaryOut:
    return CohortSummaryOut(
        id=cohort.id,
        code=cohort.code,
        name=cohort.name,
        start_date=cohort.start_date,
        end_date=cohort.end_date,
        timezone=cohort.timezone,
        my_roles=sorted(principal.cohort_roles(cohort.id)),
    )


def squad_out(db: Session, squad: Squad) -> SquadOut:
    rows = db.execute(
        select(User, CohortMembership.pathway)
        .join(SquadMember, SquadMember.user_id == User.id)
        .outerjoin(
            CohortMembership,
            (CohortMembership.user_id == User.id)
            & (CohortMembership.cohort_id == squad.cohort_id)
            & (CohortMembership.role == "student"),
        )
        .where(SquadMember.squad_id == squad.id)
        .order_by(User.display_name)
    ).all()
    return SquadOut(
        id=squad.id,
        name=squad.name,
        members=[SquadMemberOut(user_id=u.id, display_name=u.display_name, pathway=p) for u, p in rows],
    )


def student_squad(db: Session, cohort_id: int, user_id: int) -> Squad | None:
    return db.scalar(
        select(Squad)
        .join(SquadMember, SquadMember.squad_id == Squad.id)
        .where(Squad.cohort_id == cohort_id, SquadMember.user_id == user_id)
    )


def _require_student(db: Session, principal: Principal, action: str) -> list[CohortMembership]:
    memberships = principal.student_memberships()
    if not memberships:
        raise deny(
            db,
            principal,
            action=action,
            entity_type="student_portal",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason="not enrolled as a student",
        )
    return memberships


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> DashboardOut:
    memberships = _require_student(db, principal, "student.dashboard")
    enrollments, assignments = [], []
    current_module = None
    schedule = []
    lessons_available = 0
    for m in memberships:
        cohort = db.get(Cohort, m.cohort_id)
        assert cohort is not None
        squad = student_squad(db, cohort.id, principal.id)
        enrollments.append(
            EnrollmentOut(
                cohort=cohort_summary(cohort, principal),
                pathway=m.pathway or "",
                squad=squad_out(db, squad) if squad else None,
            )
        )
        for a, t in work.student_assignments(db, cohort.id, m.pathway or ""):
            assignments.append(work.summarize(db, a, t, cohort.course_version_id, principal.id))
        if not schedule:
            schedule = schedule_out(db, cohort.course_version_id, cohort.start_date)
            modules = module_summaries(db, cohort.course_version_id)
            open_codes = [a.module_code for a in assignments if a.status in ("not_started", "draft")]
            current_module = next((mod for mod in modules if mod.code in open_codes), None)
            lessons_available = sum(
                1
                for ls in db.scalars(
                    select(Lesson).join(Module).where(Module.course_version_id == cohort.course_version_id)
                )
                if content_visible(ls.approval_status)
            )
    reviewed = (
        db.scalar(
            select(func.count()).select_from(LessonProgress).where(LessonProgress.user_id == principal.id)
        )
        or 0
    )
    submissions = (
        db.scalar(select(func.count()).select_from(Submission).where(Submission.student_id == principal.id))
        or 0
    )
    released = (
        db.scalar(
            select(func.count(func.distinct(EvaluationRecord.submission_id)))
            .select_from(FeedbackRelease)
            .join(EvaluationRecord, EvaluationRecord.id == FeedbackRelease.evaluation_record_id)
            .join(Submission, Submission.id == EvaluationRecord.submission_id)
            .where(Submission.student_id == principal.id)
        )
        or 0
    )
    return DashboardOut(
        display_name=principal.user.display_name,
        enrollments=enrollments,
        current_module=current_module,
        assignments=assignments,
        schedule=schedule,
        lessons_reviewed=reviewed,
        lessons_available=lessons_available,
        submissions=submissions,
        feedback_released=released,
        progress_notice=PROGRESS_NOTICE,
    )


@router.get("/assessments", response_model=list[StudentAssessmentOut])
def assessments(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[StudentAssessmentOut]:
    _require_student(db, principal, "student.assessments")
    subs = db.scalars(
        select(Submission)
        .where(Submission.student_id == principal.id)
        .order_by(Submission.submitted_at.desc())
    ).all()
    out = []
    for sub in subs:
        _a, template, cohort = ev.submission_context(db, sub)
        _ex, inst_code = work.assignment_codes(db, template)
        released = ev.evaluation_history(db, sub.id, released_only=True)
        feedback = released[-1] if released else None
        objectives = ev.objectives_in_scope(db, cohort, template, inst_code)
        out.append(
            StudentAssessmentOut(
                submission=work.submission_out(db, sub),
                feedback=feedback,
                objectives=ev.objective_status(objectives, feedback),
            )
        )
    return out


# --- squad collaboration ------------------------------------------------------------------------
def _squad_context(db: Session, principal: Principal, action: str) -> tuple[int, Squad]:
    for m in _require_student(db, principal, action):
        squad = student_squad(db, m.cohort_id, principal.id)
        if squad is not None:
            return m.cohort_id, squad
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No squad assignment")


def _handoff_out(db: Session, h: Handoff, cohort_id: int) -> HandoffOut:
    pathway = db.scalar(
        select(CohortMembership.pathway).where(
            CohortMembership.cohort_id == cohort_id,
            CohortMembership.user_id == h.author_id,
            CohortMembership.role == "student",
        )
    )
    return HandoffOut(
        id=h.id,
        author_name=h.author.display_name,
        author_pathway=pathway,
        recipient_name=h.recipient.display_name if h.recipient else None,
        established=h.established,
        assessed=h.assessed,
        unknown=h.unknown,
        next_action_owner=h.next_action_owner,
        cited_evidence=list(h.cited_evidence),
        created_at=h.created_at,
    )


@router.get("/squad", response_model=SquadViewOut)
def squad_view(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> SquadViewOut:
    cohort_id, squad = _squad_context(db, principal, "squad.view")
    handoffs = db.scalars(
        select(Handoff).where(Handoff.squad_id == squad.id).order_by(Handoff.created_at.desc())
    )
    return SquadViewOut(
        cohort_id=cohort_id,
        squad=squad_out(db, squad),
        handoffs=[_handoff_out(db, h, cohort_id) for h in handoffs],
    )


@router.post("/squad/handoffs", response_model=HandoffOut, dependencies=[Depends(require_csrf_header)])
def create_handoff(
    body: HandoffIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> HandoffOut:
    """Each handoff is attributed to its individual author (recorded individual contribution)."""
    cohort_id, squad = _squad_context(db, principal, "handoff.create")
    member_ids = {m.user_id for m in db.scalars(select(SquadMember).where(SquadMember.squad_id == squad.id))}
    if body.recipient_id is not None and (
        body.recipient_id not in member_ids or body.recipient_id == principal.id
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Recipient must be another member of your squad"
        )
    if not (body.established.strip() or body.assessed.strip() or body.unknown.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Handoff is empty")
    allowed = released_evidence_codes(db, cohort_id)
    if set(body.cited_evidence) - allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cited evidence must be released evidence")
    active = active_cohort_case(db, cohort_id)
    if active is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No case active")
    h = Handoff(
        squad_id=squad.id,
        case_id=active[2].id,
        author_id=principal.id,
        recipient_id=body.recipient_id,
        established=body.established,
        assessed=body.assessed,
        unknown=body.unknown,
        next_action_owner=body.next_action_owner,
        cited_evidence=list(dict.fromkeys(body.cited_evidence)),
    )
    db.add(h)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="handoff.create",
        entity_type="handoff",
        entity_id=h.id,
        cohort_id=cohort_id,
        details={"squad_id": squad.id},
    )
    db.commit()
    db.refresh(h)
    return _handoff_out(db, h, cohort_id)
