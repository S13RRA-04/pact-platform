"""Release plans: authoring and package approval, cohort activation, instructor control, student challenges.

Authority:
- Curriculum Editor / Program Administrator: author plans on draft versions, submit, clone.
- Content Approver: decides plan approval (via /api/admin/approvals, as for other content).
- Program Administrator: activates a scenario version for a cohort.
- Instructors of the cohort (and Program Administrators): release, hold, resume, withdraw.
- Evaluators of the cohort: read the cohort plan, including answer keys.
- Students: see released challenges/debriefs for their pathway; never answer keys or unreleased items.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models import (
    ApprovalRequest,
    AssessmentInstrument,
    Case,
    Cohort,
    CohortCase,
    CurriculumDocument,
    Inject,
    Module,
    ReleaseItem,
    ScenarioVersion,
    User,
)
from app.schemas.release import (
    ActionIn,
    ActivateIn,
    CloneIn,
    CohortPlanOut,
    CohortReleaseOut,
    Option,
    ReleaseItemIn,
    ReleaseItemOut,
    ScenarioVersionDetailOut,
    ScenarioVersionOut,
    StudentChallengeOut,
)
from app.security.authz import (
    STAFF_ROLES,
    Principal,
    deny,
    get_principal,
    require_csrf_header,
    require_global_role,
)
from app.services import release_plan as rp

router = APIRouter(tags=["release-plans"], dependencies=[Depends(require_csrf_header)])

AUTHORS = {"curriculum_editor", "program_admin"}
READERS = {"curriculum_editor", "content_approver", "program_admin"}


# --- helpers -----------------------------------------------------------------------------------------
def _version_or_404(db: Session, sv_id: int) -> ScenarioVersion:
    sv = db.get(ScenarioVersion, sv_id)
    if sv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scenario version not found")
    return sv


def _pending_approval(db: Session, sv_id: int) -> ApprovalRequest | None:
    return db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.entity_type == "scenario_version",
            ApprovalRequest.entity_id == sv_id,
            ApprovalRequest.status == "pending",
        )
    )


def _summary(db: Session, sv: ScenarioVersion) -> ScenarioVersionOut:
    case = db.get(Case, sv.case_id)
    assert case is not None
    pending = _pending_approval(db, sv.id)
    cohorts = db.scalars(
        select(Cohort.code)
        .join(CohortCase, CohortCase.cohort_id == Cohort.id)
        .where(CohortCase.scenario_version_id == sv.id)
        .order_by(Cohort.code)
    )
    return ScenarioVersionOut(
        id=sv.id,
        case_code=case.code,
        case_title=case.title,
        version_label=sv.version_label,
        approval_status=sv.approval_status,
        locked=sv.locked,
        item_count=len(rp.items_for(db, sv.id)),
        pending_approval_id=pending.id if pending else None,
        cohorts_using=list(cohorts),
    )


def _detail(db: Session, sv: ScenarioVersion) -> ScenarioVersionDetailOut:
    items = rp.items_for(db, sv.id)
    blocks = sorted(
        {
            b
            for b in db.scalars(
                select(CurriculumDocument.release_block).where(
                    CurriculumDocument.audience == "student", CurriculumDocument.release_block.is_not(None)
                )
            )
        }
    )
    instruments = {
        i.code: i.name for i in db.scalars(select(AssessmentInstrument).order_by(AssessmentInstrument.code))
    }
    modules = {m.code: m.title for m in db.scalars(select(Module).order_by(Module.code))}
    return ScenarioVersionDetailOut(
        **_summary(db, sv).model_dump(),
        plan_sha256=rp.plan_sha256(items),
        items=[ReleaseItemOut(id=i.id, **{f: getattr(i, f) for f in rp.ITEM_FIELDS}) for i in items],
        injects=[
            Option(code=i.code, label=f"{i.title} ({i.approval_status})")
            for i in db.scalars(
                select(Inject).where(Inject.scenario_version_id == sv.id).order_by(Inject.sequence)
            )
        ],
        document_blocks=[Option(code=b, label=b) for b in blocks],
        instruments=[Option(code=c, label=n) for c, n in instruments.items()],
        modules=[Option(code=c, label=t) for c, t in modules.items()],
    )


def _trigger_text(item: ReleaseItem) -> str:
    return {
        "manual": "Released by instructor",
        "scheduled": f"{item.trigger_day} {item.trigger_time} (cohort time)",
        "lesson_gate": f"When {item.trigger_module_code} is {item.trigger_lesson_state}",
        "after_item": f"After {item.trigger_after_code}",
    }[item.trigger_type]


# --- authoring ------------------------------------------------------------------------------------------
@router.get("/api/admin/scenario-versions", response_model=list[ScenarioVersionOut])
def list_versions(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_global_role(db, principal, READERS | {"program_admin"}, "scenario.list")
    return [_summary(db, sv) for sv in db.scalars(select(ScenarioVersion).order_by(ScenarioVersion.id))]


@router.get("/api/admin/scenario-versions/{sv_id}", response_model=ScenarioVersionDetailOut)
def version_detail(sv_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_global_role(db, principal, READERS, "scenario.view")
    return _detail(db, _version_or_404(db, sv_id))


@router.post(
    "/api/admin/scenario-versions/{sv_id}/items", response_model=ScenarioVersionDetailOut, status_code=201
)
def create_item(
    sv_id: int,
    body: ReleaseItemIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    require_global_role(db, principal, AUTHORS, "release_item.create")
    sv = _version_or_404(db, sv_id)
    rp.require_editable(sv)
    data = rp.normalize_item(db, sv, body.model_dump(), None)
    item = ReleaseItem(scenario_version_id=sv.id, **data)
    db.add(item)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="release_item.create",
        entity_type="release_item",
        entity_id=item.id,
        details={"scenario_version_id": sv.id, "code": item.code, "type": item.item_type},
    )
    db.commit()
    return _detail(db, sv)


@router.put("/api/admin/scenario-versions/{sv_id}/items/{item_id}", response_model=ScenarioVersionDetailOut)
def update_item(
    sv_id: int,
    item_id: int,
    body: ReleaseItemIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    require_global_role(db, principal, AUTHORS, "release_item.update")
    sv = _version_or_404(db, sv_id)
    rp.require_editable(sv)
    item = db.get(ReleaseItem, item_id)
    if item is None or item.scenario_version_id != sv.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release item not found")
    data = rp.normalize_item(db, sv, body.model_dump(), item.id)
    dependents = [
        i.code
        for i in rp.items_for(db, sv.id)
        if item.code != data["code"] and item.code in (i.trigger_after_code, i.answer_for_code)
    ]
    if dependents:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot rename: referenced by {', '.join(dependents)}")
    for k, v in data.items():
        setattr(item, k, v)
    item.updated_at = rp._now()
    audit.record(
        db,
        actor_id=principal.id,
        action="release_item.update",
        entity_type="release_item",
        entity_id=item.id,
        details={"scenario_version_id": sv.id, "code": item.code},
    )
    db.commit()
    return _detail(db, sv)


@router.delete(
    "/api/admin/scenario-versions/{sv_id}/items/{item_id}", response_model=ScenarioVersionDetailOut
)
def delete_item(
    sv_id: int, item_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    require_global_role(db, principal, AUTHORS, "release_item.delete")
    sv = _version_or_404(db, sv_id)
    rp.require_editable(sv)
    item = db.get(ReleaseItem, item_id)
    if item is None or item.scenario_version_id != sv.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release item not found")
    dependents = [
        i.code for i in rp.items_for(db, sv.id) if item.code in (i.trigger_after_code, i.answer_for_code)
    ]
    if dependents:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Referenced by {', '.join(dependents)}; change those first"
        )
    db.delete(item)
    audit.record(
        db,
        actor_id=principal.id,
        action="release_item.delete",
        entity_type="release_item",
        entity_id=item_id,
        details={"scenario_version_id": sv.id, "code": item.code},
    )
    db.commit()
    return _detail(db, sv)


@router.post("/api/admin/scenario-versions/{sv_id}/submit", response_model=ScenarioVersionDetailOut)
def submit_plan(sv_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Submit the whole plan for content approval. Editing is blocked while it is pending."""
    require_global_role(db, principal, AUTHORS, "scenario.submit")
    sv = _version_or_404(db, sv_id)
    rp.require_editable(sv)
    items = rp.items_for(db, sv.id)
    if not items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Add at least one release item before submitting"
        )
    case = db.get(Case, sv.case_id)
    assert case is not None
    digest = rp.plan_sha256(items)
    sv.approval_status = "pending"
    db.add(
        ApprovalRequest(
            workflow="content",
            entity_type="scenario_version",
            entity_id=sv.id,
            entity_code=f"{case.code}/v{sv.version_label}",
            entity_sha256=digest,
            summary=f"Approve release plan for {case.code} v{sv.version_label} ({len(items)} items)",
            requested_by_id=principal.id,
        )
    )
    audit.record(
        db,
        actor_id=principal.id,
        action="scenario.submit",
        entity_type="scenario_version",
        entity_id=sv.id,
        details={"plan_sha256": digest, "items": len(items)},
    )
    db.commit()
    return _detail(db, sv)


@router.post(
    "/api/admin/scenario-versions/{sv_id}/clone", response_model=ScenarioVersionDetailOut, status_code=201
)
def clone(
    sv_id: int, body: CloneIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    require_global_role(db, principal, AUTHORS, "scenario.clone")
    new = rp.clone_version(db, _version_or_404(db, sv_id), body.version_label, principal.id)
    db.commit()
    return _detail(db, new)


# --- cohort activation and control ------------------------------------------------------------------------
@router.post("/api/admin/cohorts/{cohort_id}/activate-scenario", response_model=CohortPlanOut)
def activate(
    cohort_id: int,
    body: ActivateIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    require_global_role(db, principal, {"program_admin"}, "scenario.activate")
    cohort = db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cohort not found")
    rp.activate(db, cohort, _version_or_404(db, body.scenario_version_id), principal.id)
    rp.process_due(db, cohort.id)
    db.commit()
    return _plan(db, principal, cohort)


def _cohort_access(db: Session, principal: Principal, cohort_id: int, *, control: bool) -> Cohort:
    roles = principal.cohort_roles(cohort_id)
    admin = "program_admin" in principal.global_roles
    allowed = admin or ("instructor" in roles if control else bool(roles & STAFF_ROLES))
    cohort = db.get(Cohort, cohort_id)
    if not allowed or cohort is None:
        raise deny(
            db,
            principal,
            action="release_plan.control" if control else "release_plan.view",
            entity_type="cohort",
            entity_id=cohort_id,
            cohort_id=cohort_id,
            code=status.HTTP_403_FORBIDDEN if roles or admin else status.HTTP_404_NOT_FOUND,
        )
    return cohort


def _plan(db: Session, principal: Principal, cohort: Cohort) -> CohortPlanOut:
    cc = db.scalar(select(CohortCase).where(CohortCase.cohort_id == cohort.id))
    sv = db.get(ScenarioVersion, cc.scenario_version_id) if cc else None
    case = db.get(Case, sv.case_id) if sv else None
    rows = rp.cohort_rows(db, cohort.id)
    names = {
        u.id: u.display_name
        for u in db.scalars(
            select(User).where(
                User.id.in_([r.state.released_by_id for r in rows if r.state.released_by_id] or [0])
            )
        )
    }
    evidence_titles = {
        i.code: i.student_briefing
        for i in db.scalars(select(Inject).where(Inject.scenario_version_id == (sv.id if sv else 0)))
    }
    out = []
    for r in rows:
        it = r.item
        preview = (
            evidence_titles.get(it.inject_code or "", "")
            if it.item_type == "evidence_inject"
            else f"Student documents in block “{it.document_block}”"
            if it.item_type == "document_block"
            else it.body
        )
        out.append(
            CohortReleaseOut(
                item_id=it.id,
                code=it.code,
                sequence=it.sequence,
                item_type=it.item_type,
                title=it.title,
                audience=it.audience,
                trigger=_trigger_text(it),
                state=r.state.state,
                due_at=r.state.due_at,
                released_at=r.state.released_at,
                released_by=names.get(r.state.released_by_id or 0),
                withdrawn_at=r.state.withdrawn_at,
                reason=r.state.reason,
                blocked_reason=r.state.blocked_reason,
                scored=it.scored,
                preview=preview,
                instructor_notes=it.instructor_notes,
            )
        )
    can_control = "program_admin" in principal.global_roles or "instructor" in principal.cohort_roles(
        cohort.id
    )
    return CohortPlanOut(
        cohort_id=cohort.id,
        cohort_code=cohort.code,
        timezone=cohort.timezone,
        case_code=case.code if case else None,
        scenario_version=sv.version_label if sv else None,
        approval_status=sv.approval_status if sv else None,
        can_control=can_control,
        items=out,
    )


@router.get("/api/cohorts/{cohort_id}/release-plan", response_model=CohortPlanOut)
def cohort_plan(cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    cohort = _cohort_access(db, principal, cohort_id, control=False)
    if rp.process_due(db, cohort.id):
        db.commit()
    return _plan(db, principal, cohort)


@router.post("/api/cohorts/{cohort_id}/release-plan/{item_id}/{action}", response_model=CohortPlanOut)
def control(
    cohort_id: int,
    item_id: int,
    action: str,
    body: ActionIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    cohort = _cohort_access(db, principal, cohort_id, control=True)
    reason = (body.reason or "").strip() or None
    if action == "release":
        rp.release(db, cohort.id, item_id, principal.id, reason=reason)
    elif action == "hold":
        rp.hold(db, cohort.id, item_id, principal.id, reason)
    elif action == "resume":
        rp.resume(db, cohort.id, item_id, principal.id)
    elif action == "withdraw":
        if not reason:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for withdrawing released material"
            )
        rp.withdraw(db, cohort.id, item_id, principal.id, reason)
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown action")
    db.commit()
    return _plan(db, principal, cohort)


# --- students ---------------------------------------------------------------------------------------------
@router.get("/api/student/challenges", response_model=list[StudentChallengeOut])
def student_challenges(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    memberships = principal.student_memberships()
    if not memberships:
        raise deny(
            db,
            principal,
            action="challenges.list",
            entity_type="student_portal",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason="not enrolled as a student",
        )
    out = []
    for m in memberships:
        if rp.process_due(db, m.cohort_id):
            db.commit()
        for r in rp.cohort_rows(db, m.cohort_id):
            it = r.item
            if (
                r.state.state == "released"
                and it.item_type in ("challenge", "debrief")
                and it.audience in ("all_students", m.pathway)
            ):
                out.append(
                    StudentChallengeOut(
                        code=it.code,
                        item_type=it.item_type,
                        title=it.title,
                        body=it.body,
                        time_limit_minutes=it.time_limit_minutes,
                        instrument_code=it.instrument_code,
                        scored=it.scored,
                        released_at=r.state.released_at,
                    )
                )
    return out
