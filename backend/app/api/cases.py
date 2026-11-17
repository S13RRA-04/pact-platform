"""Case dossier and evidence library (student view = released only), plus instructor preview and release."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models import EvidenceItem, Inject, User
from app.schemas.common import (
    CaseOut,
    EvidenceOut,
    InjectBriefOut,
    ReleaseIn,
    StaffEvidenceOut,
    StaffEvidencePreviewOut,
    StaffInjectOut,
    TimelineEntryOut,
)
from app.security.authz import (
    STAFF_ROLES,
    Principal,
    deny,
    get_principal,
    require_cohort_role,
    require_csrf_header,
)
from app.services import release_plan
from app.services.visibility import active_cohort_case, released_evidence, releases

router = APIRouter(prefix="/api/cohorts/{cohort_id}", tags=["case"])
ANY_MEMBER = frozenset({"student", "instructor", "evaluator"})


def _evidence_out(item: EvidenceItem, release: str, released_at: object) -> EvidenceOut:
    return EvidenceOut(
        code=item.code,
        title=item.title,
        source_type=item.source_type,
        observed_at=item.observed_at,
        observed_timezone=item.observed_timezone,
        observed_as_recorded=item.observed_as_recorded,
        provenance=item.provenance,
        limitations=item.limitations,
        content=item.content,
        release=release,
        released_at=released_at,  # type: ignore[arg-type]
    )


@router.get("/case", response_model=CaseOut)
def case_dossier(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CaseOut:
    require_cohort_role(db, principal, cohort_id, ANY_MEMBER, "case.view")
    active = active_cohort_case(db, cohort_id)
    if active is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No case active for this cohort")
    cc, sv, case = active
    evidence = released_evidence(db, cohort_id)
    rel = releases(db, cohort_id)
    injects = db.scalars(select(Inject).where(Inject.id.in_(list(rel) or [0])).order_by(Inject.sequence))
    return CaseOut(
        cohort_id=cohort_id,
        code=case.code,
        title=case.title,
        summary=case.summary,
        victim_organization=case.victim_organization,
        fictional_disclaimer=case.fictional_disclaimer,
        scenario_version=sv.version_label,
        activated_at=cc.activated_at,
        evidence_count=len(evidence),
        updates=[
            InjectBriefOut(
                code=i.code,
                title=i.title,
                student_briefing=i.student_briefing,
                released_at=rel[i.id].released_at,
            )
            for i in injects
        ],
        timeline=sorted(
            (
                TimelineEntryOut(
                    observed_at=e.observed_at,
                    evidence_code=e.code,
                    title=e.title,
                    source_type=e.source_type,
                    observed_as_recorded=e.observed_as_recorded,
                )
                for e, _, _ in evidence
                if e.observed_at is not None  # undated records appear in the library only
            ),
            key=lambda t: t.observed_at,
        ),
    )


@router.get("/evidence", response_model=list[EvidenceOut])
def evidence_library(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[EvidenceOut]:
    require_cohort_role(db, principal, cohort_id, ANY_MEMBER, "evidence.list")
    return [_evidence_out(i, r, at) for i, r, at in released_evidence(db, cohort_id)]


@router.get("/evidence/{code}", response_model=EvidenceOut)
def evidence_item(
    cohort_id: int, code: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> EvidenceOut:
    require_cohort_role(db, principal, cohort_id, ANY_MEMBER, "evidence.view")
    for i, r, at in released_evidence(db, cohort_id):
        if i.code == code:
            return _evidence_out(i, r, at)
    raise deny(
        db,
        principal,
        action="evidence.view",
        entity_type="evidence",
        entity_id=code,
        cohort_id=cohort_id,
        reason="unreleased or nonexistent",
    )


# --- staff: preview + release ------------------------------------------------------------------
def _staff_preview(db: Session, cohort_id: int) -> StaffEvidencePreviewOut:
    active = active_cohort_case(db, cohort_id)
    if active is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No case active for this cohort")
    cc, sv, case = active
    rel = releases(db, cohort_id)
    injects = {
        i.id: i
        for i in db.scalars(
            select(Inject).where(Inject.scenario_version_id == sv.id).order_by(Inject.sequence)
        )
    }
    items = db.scalars(
        select(EvidenceItem).where(EvidenceItem.scenario_version_id == sv.id).order_by(EvidenceItem.sequence)
    ).all()
    users = {
        u.id: u.display_name
        for u in db.scalars(select(User).where(User.id.in_([r.released_by_id for r in rel.values()] or [0])))
    }
    evidence = []
    for it in items:
        inj = injects.get(it.inject_id) if it.inject_id else None
        released = inj is None or inj.id in rel
        released_at = cc.activated_at if inj is None else (rel[inj.id].released_at if inj.id in rel else None)
        base = _evidence_out(it, inj.code if inj else "baseline", released_at)
        evidence.append(
            StaffEvidenceOut(
                **base.model_dump(),
                instructor_notes=it.instructor_notes,
                released=released,
                inject_approval_status=inj.approval_status if inj else None,
            )
        )
    return StaffEvidencePreviewOut(
        cohort_id=cohort_id,
        case_code=case.code,
        case_title=case.title,
        instructor_overview=case.instructor_overview,
        scenario_version=sv.version_label,
        evidence=evidence,
        injects=[
            StaffInjectOut(
                id=i.id,
                code=i.code,
                title=i.title,
                student_briefing=i.student_briefing,
                instructor_notes=i.instructor_notes,
                approval_status=i.approval_status,
                released=i.id in rel,
                released_at=rel[i.id].released_at if i.id in rel else None,
                released_by=users.get(rel[i.id].released_by_id) if i.id in rel else None,
                evidence_codes=[e.code for e in items if e.inject_id == i.id],
            )
            for i in injects.values()
        ],
    )


@router.get("/staff/evidence-preview", response_model=StaffEvidencePreviewOut)
def staff_evidence_preview(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> StaffEvidencePreviewOut:
    require_cohort_role(db, principal, cohort_id, STAFF_ROLES, "evidence.preview")
    return _staff_preview(db, cohort_id)


@router.post(
    "/staff/injects/{inject_id}/release",
    response_model=StaffInjectOut,
    dependencies=[Depends(require_csrf_header)],
)
def release_inject(
    cohort_id: int,
    inject_id: int,
    body: ReleaseIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> StaffInjectOut:
    require_cohort_role(db, principal, cohort_id, frozenset({"instructor"}), "inject.release")
    active = active_cohort_case(db, cohort_id)
    inject = db.get(Inject, inject_id)
    if active is None or inject is None or inject.scenario_version_id != active[1].id:
        raise deny(
            db,
            principal,
            action="inject.release",
            entity_type="inject",
            entity_id=inject_id,
            cohort_id=cohort_id,
            reason="inject not in cohort scenario",
        )
    if inject.approval_status != "approved":
        audit.record_denial(
            db,
            actor_id=principal.id,
            action="inject.release",
            entity_type="inject",
            entity_id=inject_id,
            cohort_id=cohort_id,
            details={"reason": f"inject approval_status={inject.approval_status}"},
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Inject has not been approved through the content approval workflow"
        )
    plan_row = next(
        (
            r
            for r in release_plan.cohort_rows(db, cohort_id)
            if r.item.item_type == "evidence_inject" and r.item.inject_code == inject.code
        ),
        None,
    )
    if plan_row is not None:
        # Same path as the release-plan screen: notifications, follow-on items, plan timeline.
        release_plan.release(db, cohort_id, plan_row.item.id, principal.id, reason=body.note)
    elif not release_plan.release_inject_to_cohort(db, cohort_id, inject, principal.id, body.note):
        raise HTTPException(status.HTTP_409_CONFLICT, "Inject already released to this cohort")
    audit.record(
        db,
        actor_id=principal.id,
        action="inject.release",
        entity_type="inject",
        entity_id=inject_id,
        cohort_id=cohort_id,
        details={"inject_code": inject.code, "note": body.note},
    )
    db.commit()
    return next(i for i in _staff_preview(db, cohort_id).injects if i.id == inject_id)
