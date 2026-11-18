"""Install Operation HARBORLINE v0.5 and retire the earlier scenarios. Development/test data only; idempotent.

- Imports the v0.5 staged packets and instructor master (curriculum archive importer) and keeps the v0.3
  exercise suite as reference documents for staff (Course Materials); v0.3 is no longer released.
- Builds scenario version 0.5: one inject per packet (on the packet's squad track), the release plan, and the
  E03/E04 P02 workspaces from the packets' own tasks.
- Retires GLASS HARBOR and HARBORLINE v0.3 (they can no longer be activated).
- With ``switch_existing``, moves cohorts running a retired version to v0.5.

Approvals recorded here are made by the synthetic Content Approver persona and say so in their decision
note. They are development approvals of synthetic data, not curriculum sign-off.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.curriculum_import.archives import import_curriculum_archives
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
    CurriculumDocumentRelease,
    Draft,
    EvidenceItem,
    Exercise,
    Inject,
    InjectRelease,
    ReleaseItem,
    ScenarioVersion,
    Squad,
    User,
)
from app.schemas.release import ReleaseItemIn
from app.seed import harborline as hb
from app.services import release_plan as rp
from app.services.background_jobs import process_scan_job

SEED_NOTE = "Synthetic seed approval for local development data (not curriculum sign-off)."
RETIRED = [("GLASS-HARBOR", None), (hb.CASE_CODE, "0.3")]  # (case code, version label or None = all)
SCENARIO_DOC_CODES = ("PKT-%", "HBL3-%", "HBL-%")
# Development squads get a case track and a search-site team so the demo shows the per-squad releases.
DEV_SQUAD_TRACKS = {
    "Alpha": ("A", "418"),
    "Bravo": ("B", "R12"),
    "Charlie": ("C", "C14"),
    "Delta": ("D", None),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _scenario_docs():
    return or_(*(CurriculumDocument.document_code.like(c) for c in SCENARIO_DOC_CODES))


def _approve_documents(db: Session, approver: User) -> int:
    """Run queued scans, then approve pending scenario documents (by code) through their approval records.

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
            ApprovalRequest.entity_id.in_(select(CurriculumDocument.id).where(_scenario_docs())),
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


def _case(db: Session, s: hb.Scenario) -> Case:
    spec = hb.case_spec(s)
    case = db.scalar(select(Case).where(Case.code == hb.CASE_CODE))
    if case is None:
        case = Case(**spec)
        db.add(case)
    else:  # the case header follows the current scenario version
        for k, v in spec.items():
            setattr(case, k, v)
    db.flush()
    return case


def _scenario(db: Session, case: Case, s: hb.Scenario) -> ScenarioVersion:
    sv = db.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.case_id == case.id, ScenarioVersion.version_label == hb.SCENARIO_VERSION
        )
    )
    if sv is not None:
        return sv
    sv = ScenarioVersion(
        case_id=case.id, version_label=hb.SCENARIO_VERSION, approval_status="draft", locked=False
    )
    db.add(sv)
    db.flush()
    for spec in hb.inject_specs(s):
        evidence = spec.pop("evidence")
        inject = Inject(scenario_version_id=sv.id, approval_status="approved", **spec)
        db.add(inject)
        db.flush()
        for ev in evidence:  # every record belongs to a packet's inject: nothing is baseline-visible
            db.add(EvidenceItem(scenario_version_id=sv.id, inject_id=inject.id, **ev))
    db.flush()
    return sv


def _templates(db: Session, s: hb.Scenario, cv_id: int) -> list[AssignmentTemplate]:
    e03 = db.scalar(select(Exercise).where(Exercise.course_version_id == cv_id, Exercise.code == "E03"))
    p02 = db.scalar(
        select(AssessmentInstrument).where(
            AssessmentInstrument.course_version_id == cv_id, AssessmentInstrument.code == "P02"
        )
    )
    assert e03 is not None and p02 is not None
    out = []
    for spec in hb.p02_templates(s):
        t = db.scalar(select(AssignmentTemplate).where(AssignmentTemplate.code == spec["code"]))
        if t is None:
            t = AssignmentTemplate(exercise_id=e03.id, instrument_id=p02.id, approval_status="draft", **spec)
            db.add(t)
        elif any(getattr(t, k) != v for k, v in spec.items()):
            for k, v in spec.items():
                setattr(t, k, v)
            t.content_version += 1  # submissions keep their own snapshot of the version they answered
        out.append(t)
    db.flush()
    return out


def _plan(db: Session, case: Case, sv: ScenarioVersion, s: hb.Scenario, editor: User, approver: User) -> None:
    if rp.items_for(db, sv.id):
        return
    for spec in hb.release_plan(s):
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


def _retired_versions(db: Session) -> list[ScenarioVersion]:
    out = []
    for code, label in RETIRED:
        case = db.scalar(select(Case).where(Case.code == code))
        if case is None:
            continue
        query = select(ScenarioVersion).where(ScenarioVersion.case_id == case.id)
        if label:
            query = query.where(ScenarioVersion.version_label == label)
        out.extend(db.scalars(query))
    return out


def _switch_cohort(
    db: Session, cohort: Cohort, old: CohortCase, case: Case, templates: list[AssignmentTemplate]
) -> None:
    """Move a development cohort off a retired version. Submissions are untouched (they keep their own
    template snapshot and cited codes); in-progress drafts written for other workspaces are cleared, and every
    scenario document released by the old plan is withdrawn (the old plan released them cohort-wide)."""
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
    for rel in db.scalars(
        select(CurriculumDocumentRelease).where(
            CurriculumDocumentRelease.cohort_id == cohort.id,
            CurriculumDocumentRelease.state == "released",
            CurriculumDocumentRelease.document_id.in_(select(CurriculumDocument.id).where(_scenario_docs())),
        )
    ):
        rel.state, rel.withdrawn_at = "withdrawn", _now()
    db.delete(old)
    keys = {t.id: {s["key"] for s in t.sections} for t in templates}
    for a in db.scalars(select(Assignment).where(Assignment.cohort_id == cohort.id)):
        a.case_id = case.id
        for d in db.scalars(select(Draft).where(Draft.assignment_id == a.id)):
            if set(d.content) - keys.get(a.template_id, set()):
                db.delete(d)
    for squad in db.scalars(select(Squad).where(Squad.cohort_id == cohort.id)):
        if squad.case_track is None and squad.name in DEV_SQUAD_TRACKS:
            squad.case_track, squad.site_team = DEV_SQUAD_TRACKS[squad.name]
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
    s = hb.load_scenario()
    reference = import_exercise_suite(db, hb.SUITE_DIR, cv.id)  # v0.3: staff reference documents
    archives = import_curriculum_archives(db, [hb.STUDENT_ZIP, hb.INSTRUCTOR_ZIP], cv.id)
    approved = _approve_documents(db, approver)

    case = _case(db, s)
    sv = _scenario(db, case, s)
    templates = _templates(db, s, cv.id)
    _plan(db, case, sv, s, editor, approver)

    retired = _retired_versions(db)
    for old_sv in retired:
        old_sv.approval_status, old_sv.locked = "retired", True

    targets = list(activate)
    if switch_existing and retired:
        for cc in db.scalars(
            select(CohortCase).where(CohortCase.scenario_version_id.in_([v.id for v in retired]))
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
        f"HARBORLINE v{sv.version_label}: {archives.imported} v0.5 documents imported "
        f"({archives.deduplicated} unchanged), {len(reference.imported)} v0.3 reference documents imported; "
        f"{approved} approved; {len(targets)} cohort(s) activated; {len(retired)} earlier version(s) retired."
    )
