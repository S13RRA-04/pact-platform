"""Install Case HARBORLINE (v0.3) and retire GLASS HARBOR. Development/test data only; idempotent.

Approvals recorded here are made by the synthetic Content Approver persona and say so in their decision
note. They are development approvals of synthetic data, not curriculum sign-off.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.curriculum_import.exercise_suite import import_exercise_suite
from app.models import (
    ApprovalRequest,
    AssessmentInstrument,
    Assignment,
    AssignmentTemplate,
    Case,
    Cohort,
    CohortCase,
    CohortReleaseItem,
    CourseVersion,
    CurriculumDocument,
    Draft,
    EvidenceItem,
    Exercise,
    Inject,
    InjectRelease,
    ReleaseItem,
    ScenarioVersion,
    User,
)
from app.schemas.release import ReleaseItemIn
from app.seed import harborline as hb
from app.services import release_plan as rp
from app.services.background_jobs import process_scan_job

SEED_NOTE = "Synthetic seed approval for local development data (not curriculum sign-off)."
RETIRED_CASE = "GLASS-HARBOR"


def _now() -> datetime:
    return datetime.now(UTC)


def _approve_suite_documents(db: Session, approver: User) -> int:
    """Run queued scans, then approve pending suite documents (by code) through their content approval records.

    Selecting by code rather than by this run's imports means a rerun also completes approvals that a
    concurrently running scan worker opened after an earlier run had finished."""
    settings = get_settings()
    while process_scan_job(db, settings):
        pass
    approved = 0
    for req in db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.entity_type == "curriculum_document",
            ApprovalRequest.status == "pending",
            ApprovalRequest.entity_id.in_(
                select(CurriculumDocument.id).where(
                    CurriculumDocument.document_code.like("PKT-%")
                    | CurriculumDocument.document_code.like("HBL3-%")
                )
            ),
        )
    ):
        doc = db.get(CurriculumDocument, req.entity_id)
        if doc is None or doc.scan_status != "clean":
            continue
        req.status, req.decided_by_id, req.decided_at, req.decision_note = (
            "approved",
            approver.id,
            _now(),
            SEED_NOTE,
        )
        doc.approval_status = "approved"
        approved += 1
    db.flush()
    return approved


def _scenario(
    db: Session, records: dict[str, hb.Record], content: hb.SuiteContent
) -> tuple[Case, ScenarioVersion]:
    case = db.scalar(select(Case).where(Case.code == hb.CASE_CODE))
    if case is None:
        case = Case(**hb.case_spec(records))
        db.add(case)
        db.flush()
    sv = db.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.case_id == case.id, ScenarioVersion.version_label == hb.SCENARIO_VERSION
        )
    )
    if sv is not None:
        return case, sv
    sv = ScenarioVersion(
        case_id=case.id, version_label=hb.SCENARIO_VERSION, approval_status="draft", locked=False
    )
    db.add(sv)
    db.flush()
    specs = {s["code"]: s for s in hb.evidence_specs(records)}
    for inj in hb.inject_specs(content):
        inject = Inject(
            scenario_version_id=sv.id,
            code=inj["code"],
            sequence=inj["sequence"],
            title=inj["title"],
            student_briefing=inj["student_briefing"],
            instructor_notes=inj["instructor_notes"],
            approval_status="approved",
        )
        db.add(inject)
        db.flush()
        for code in inj["records"]:
            db.add(EvidenceItem(scenario_version_id=sv.id, inject_id=inject.id, **specs.pop(code)))
    for spec in specs.values():  # any record not in a batch stays unreleased until added to a batch
        db.add(EvidenceItem(scenario_version_id=sv.id, inject_id=None, **spec))
    db.flush()
    return case, sv


def _templates(db: Session, content: hb.SuiteContent, cv_id: int) -> list[AssignmentTemplate]:
    e03 = db.scalar(select(Exercise).where(Exercise.course_version_id == cv_id, Exercise.code == "E03"))
    p02 = db.scalar(
        select(AssessmentInstrument).where(
            AssessmentInstrument.course_version_id == cv_id, AssessmentInstrument.code == "P02"
        )
    )
    assert e03 is not None and p02 is not None
    out = []
    for spec in hb.e03_templates(content):
        t = db.scalar(select(AssignmentTemplate).where(AssignmentTemplate.code == spec["code"]))
        if t is None:
            t = AssignmentTemplate(exercise_id=e03.id, instrument_id=p02.id, approval_status="draft", **spec)
            db.add(t)
        elif t.sections != spec["sections"] or t.instructions != spec["instructions"]:
            for k, v in spec.items():
                setattr(t, k, v)
            t.content_version += 1  # submissions keep their own snapshot of the version they answered
        out.append(t)
    db.flush()
    return out


def _plan(
    db: Session, case: Case, sv: ScenarioVersion, content: hb.SuiteContent, editor: User, approver: User
) -> None:
    if rp.items_for(db, sv.id):
        return
    for spec in hb.release_plan(content):
        data = rp.normalize_item(db, sv, ReleaseItemIn(**spec).model_dump(), None)
        db.add(ReleaseItem(scenario_version_id=sv.id, **data))
        db.flush()
    db.add(
        ApprovalRequest(
            workflow="content",
            entity_type="scenario_version",
            entity_id=sv.id,
            entity_code=f"{case.code}/v{sv.version_label}",
            entity_sha256=rp.plan_sha256(rp.items_for(db, sv.id)),
            summary=f"Approve release plan for {case.code} v{sv.version_label}",
            status="approved",
            requested_by_id=editor.id,
            decided_by_id=approver.id,
            decided_at=_now(),
            decision_note=SEED_NOTE,
        )
    )
    sv.approval_status, sv.locked = "approved", True
    db.flush()


def _switch_cohort(
    db: Session, cohort: Cohort, old: CohortCase, case: Case, templates: list[AssignmentTemplate]
) -> None:
    """Move a development cohort from GLASS HARBOR to HARBORLINE. Submissions are untouched (they keep their
    own template snapshot and cited codes); in-progress drafts written for the old workspaces are cleared."""
    old_injects = select(Inject.id).where(Inject.scenario_version_id == old.scenario_version_id)
    db.execute(
        delete(InjectRelease).where(
            InjectRelease.cohort_id == cohort.id, InjectRelease.inject_id.in_(old_injects)
        )
    )
    old_items = select(ReleaseItem.id).where(ReleaseItem.scenario_version_id == old.scenario_version_id)
    db.execute(
        delete(CohortReleaseItem).where(
            CohortReleaseItem.cohort_id == cohort.id, CohortReleaseItem.item_id.in_(old_items)
        )
    )
    db.delete(old)
    keys = {t.id: {s["key"] for s in t.sections} for t in templates}
    for a in db.scalars(select(Assignment).where(Assignment.cohort_id == cohort.id)):
        a.case_id = case.id
        for d in db.scalars(select(Draft).where(Draft.assignment_id == a.id)):
            if set(d.content) - keys.get(a.template_id, set()):
                db.delete(d)
    db.flush()


def install_harborline(
    db: Session, *, activate: list[tuple[Cohort, int]] = (), switch_existing: bool = False
) -> str:
    users = {
        u.username: u
        for u in db.scalars(select(User).where(User.username.in_(["curr.ortega", "appr.whitfield"])))
    }
    editor, approver = users["curr.ortega"], users["appr.whitfield"]
    cv = db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    assert cv is not None
    if not hb.SUITE_DIR.exists():
        raise RuntimeError(f"HARBORLINE v0.3 source not found at {hb.SUITE_DIR}")
    imported = import_exercise_suite(db, hb.SUITE_DIR, cv.id)
    approved = _approve_suite_documents(db, approver)

    records, content = hb.load_records(), hb.load_suite()
    case, sv = _scenario(db, records, content)
    templates = _templates(db, content, cv.id)
    _plan(db, case, sv, content, editor, approver)

    # Retire GLASS HARBOR: its versions can no longer be activated.
    retired = db.scalar(select(Case).where(Case.code == RETIRED_CASE))
    if retired is not None:
        for old_sv in db.scalars(select(ScenarioVersion).where(ScenarioVersion.case_id == retired.id)):
            old_sv.approval_status, old_sv.locked = "retired", True

    targets = list(activate)
    if switch_existing and retired is not None:
        old_versions = select(ScenarioVersion.id).where(ScenarioVersion.case_id == retired.id)
        for cc in db.scalars(
            select(CohortCase).where(CohortCase.scenario_version_id.in_(old_versions))
        ).all():
            cohort = db.get(Cohort, cc.cohort_id)
            actor = cc.activated_by_id or editor.id
            _switch_cohort(db, cohort, cc, case, templates)
            targets.append((cohort, actor))
    for cohort, actor_id in targets:
        rp.activate(db, cohort, sv, actor_id)
    rp.process_due(db)
    db.commit()
    return (
        f"HARBORLINE v{sv.version_label}: {len(imported.imported)} suite documents imported "
        f"({approved} approved, {imported.unchanged} unchanged); {len(targets)} cohort(s) activated; "
        f"GLASS HARBOR {'retired' if retired else 'not present'}."
    )
