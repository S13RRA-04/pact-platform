"""Release plans: authoring, package approval, cohort activation, and per-cohort release control.

Rules enforced here (not in the UI):
- A plan can only be edited while its scenario version is an unlocked draft. Approval locks it; changes
  after approval go into a cloned new version.
- Activation requires an approved, locked version. A cohort runs one scenario version.
- Answer keys (audience "staff") can never be released to students.
- Evidence injects also need their own content approval; scored challenges need the instrument to be
  authorized for scored use (assessment authorization is a separate workflow).
- "after_item" items open only after their prerequisite is released, and open automatically when it is.
- Automatic triggers never raise: if an item cannot open, the reason is recorded on the cohort's item state
  and in the audit log so the instructor sees it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import (
    AssessmentInstrument,
    Assignment,
    AssignmentTemplate,
    Case,
    Cohort,
    CohortCase,
    CohortMembership,
    CohortReleaseItem,
    CurriculumDocument,
    CurriculumDocumentRelease,
    EvidenceItem,
    Exercise,
    Inject,
    InjectRelease,
    Notification,
    NotificationPreference,
    ReleaseItem,
    ScenarioVersion,
    ScheduleBlock,
)
from app.models.release import DAYS

STUDENT_AUDIENCES = ("all_students", "investigator", "analyst")
ITEM_FIELDS = (
    "code",
    "sequence",
    "item_type",
    "title",
    "audience",
    "trigger_type",
    "trigger_day",
    "trigger_time",
    "trigger_module_code",
    "trigger_lesson_state",
    "trigger_after_code",
    "inject_code",
    "document_block",
    "body",
    "time_limit_minutes",
    "instrument_code",
    "scored",
    "answer_for_code",
    "instructor_notes",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


# --- authoring ------------------------------------------------------------------------------------
def items_for(db: Session, sv_id: int) -> list[ReleaseItem]:
    return list(
        db.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.scenario_version_id == sv_id)
            .order_by(ReleaseItem.sequence, ReleaseItem.id)
        )
    )


def plan_sha256(items: list[ReleaseItem]) -> str:
    canonical = [{f: getattr(i, f) for f in ITEM_FIELDS} for i in sorted(items, key=lambda i: i.code)]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_editable(sv: ScenarioVersion) -> None:
    if sv.locked or sv.approval_status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This scenario version is approved and locked. Clone it to make changes.",
        )


def normalize_item(
    db: Session, sv: ScenarioVersion, data: dict[str, Any], item_id: int | None
) -> dict[str, Any]:
    """Validate a release item and clear fields that do not apply to its type/trigger."""
    d = dict(data)
    t, trig = d["item_type"], d["trigger_type"]
    others = {i.code: i for i in items_for(db, sv.id) if i.id != item_id}
    if d["code"] in others:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Item code {d['code']} already exists in this version")

    # Type rules
    if t == "answer_key":
        d["audience"], d["trigger_type"], trig = "staff", "manual", "manual"
        if d.get("answer_for_code") and d["answer_for_code"] not in others:
            raise _bad("Answer key must reference an item code in this version")
    elif d["audience"] == "staff":
        raise _bad("Only answer keys are staff-only; choose a student audience")
    if t == "evidence_inject":
        if not d.get("inject_code"):
            raise _bad("Evidence items need an inject code")
        if not db.scalar(
            select(Inject.id).where(Inject.scenario_version_id == sv.id, Inject.code == d["inject_code"])
        ):
            raise _bad(f"Inject {d['inject_code']} does not exist in this scenario version")
        d["audience"] = "all_students"  # case evidence is shared by both pathways
    else:
        d["inject_code"] = None
    if t == "document_block":
        if not d.get("document_block"):
            raise _bad("Document items need a document release block")
        d["audience"] = "all_students"
    else:
        d["document_block"] = None
    if t in ("challenge", "debrief", "answer_key"):
        if not (d.get("body") or "").strip():
            raise _bad("Write the content students (or staff) will see")
    if t != "challenge":
        d["time_limit_minutes"], d["scored"] = None, False
    if d.get("scored") and not d.get("instrument_code"):
        raise _bad("A scored challenge must name the assessment instrument it is scored against")
    if d.get("instrument_code") and not db.scalar(
        select(AssessmentInstrument.id).where(AssessmentInstrument.code == d["instrument_code"]).limit(1)
    ):
        raise _bad(f"Unknown assessment instrument {d['instrument_code']}")
    if t != "answer_key":
        d["answer_for_code"] = None

    # Trigger rules
    for f in (
        "trigger_day",
        "trigger_time",
        "trigger_module_code",
        "trigger_lesson_state",
        "trigger_after_code",
    ):
        d.setdefault(f, None)
    if trig != "scheduled":
        d["trigger_day"] = d["trigger_time"] = None
    elif not (d["trigger_day"] in DAYS and _valid_time(d["trigger_time"])):
        raise _bad("Scheduled items need a course day (Mon–Fri) and a local time (HH:MM)")
    if trig != "lesson_gate":
        d["trigger_module_code"] = d["trigger_lesson_state"] = None
    elif not (d["trigger_module_code"] and d["trigger_lesson_state"] in ("released", "taught")):
        raise _bad("Lesson-stage items need a module code and a stage (released or taught)")
    if trig != "after_item":
        d["trigger_after_code"] = None
    else:
        after = d["trigger_after_code"]
        if after not in others:
            raise _bad("'After item' must reference another item code in this version")
        seen, cur = {d["code"]}, after  # reject dependency cycles
        while cur:
            if cur in seen:
                raise _bad("This dependency would create a cycle")
            seen.add(cur)
            nxt = others.get(cur)
            cur = nxt.trigger_after_code if nxt and nxt.trigger_type == "after_item" else None
    return d


def _valid_time(value: str | None) -> bool:
    try:
        time.fromisoformat(value or "")
        return len(value or "") == 5
    except ValueError:
        return False


def clone_version(db: Session, sv: ScenarioVersion, label: str, actor_id: int) -> ScenarioVersion:
    """New draft version with copies of the injects, evidence and release plan."""
    if db.scalar(
        select(ScenarioVersion.id).where(
            ScenarioVersion.case_id == sv.case_id, ScenarioVersion.version_label == label
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Version {label} already exists for this case")
    new = ScenarioVersion(case_id=sv.case_id, version_label=label, approval_status="draft", locked=False)
    db.add(new)
    db.flush()
    inject_map: dict[int, int] = {}
    for inj in db.scalars(select(Inject).where(Inject.scenario_version_id == sv.id)):
        copy = Inject(
            scenario_version_id=new.id,
            code=inj.code,
            sequence=inj.sequence,
            title=inj.title,
            student_briefing=inj.student_briefing,
            instructor_notes=inj.instructor_notes,
            approval_status="draft",
        )
        db.add(copy)
        db.flush()
        inject_map[inj.id] = copy.id
    evidence_cols = (
        "code",
        "sequence",
        "title",
        "source_type",
        "observed_at",
        "observed_timezone",
        "observed_as_recorded",
        "provenance",
        "limitations",
        "content",
        "instructor_notes",
    )
    for ev in db.scalars(select(EvidenceItem).where(EvidenceItem.scenario_version_id == sv.id)):
        db.add(
            EvidenceItem(
                scenario_version_id=new.id,
                inject_id=inject_map.get(ev.inject_id) if ev.inject_id else None,
                **{c: getattr(ev, c) for c in evidence_cols},
            )
        )
    for item in items_for(db, sv.id):
        db.add(ReleaseItem(scenario_version_id=new.id, **{f: getattr(item, f) for f in ITEM_FIELDS}))
    audit.record(
        db,
        actor_id=actor_id,
        action="scenario_version.clone",
        entity_type="scenario_version",
        entity_id=new.id,
        details={"from_version_id": sv.id, "label": label},
    )
    db.flush()
    return new


# --- activation -----------------------------------------------------------------------------------
def _local_due(cohort: Cohort, day: str, hhmm: str) -> datetime:
    local_date = cohort.start_date + timedelta(days=DAYS.index(day))
    local = datetime.combine(local_date, time.fromisoformat(hhmm), tzinfo=ZoneInfo(cohort.timezone))
    return local.astimezone(UTC)


def activate(db: Session, cohort: Cohort, sv: ScenarioVersion, actor_id: int) -> CohortCase:
    """Attach an approved scenario version to a cohort: case, assignments and per-cohort release states.

    Idempotent for the same version; refuses to switch a cohort to a different version.
    """
    if sv.approval_status != "approved" or not sv.locked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only an approved, locked scenario version can be activated for a cohort",
        )
    current = db.scalar(select(CohortCase).where(CohortCase.cohort_id == cohort.id))
    if current is not None and current.scenario_version_id != sv.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This cohort already runs another scenario version; switching mid-course is not supported",
        )
    case = db.get(Case, sv.case_id)
    assert case is not None
    if current is None:
        current = CohortCase(cohort_id=cohort.id, scenario_version_id=sv.id, activated_by_id=actor_id)
        db.add(current)
    _ensure_assignments(db, cohort, case)
    existing = {
        r.item_id
        for r in db.scalars(select(CohortReleaseItem).where(CohortReleaseItem.cohort_id == cohort.id))
    }
    for item in items_for(db, sv.id):
        if item.id in existing:
            continue
        due = (
            _local_due(cohort, item.trigger_day, item.trigger_time)
            if item.trigger_type == "scheduled"
            else None
        )
        row = CohortReleaseItem(cohort_id=cohort.id, item_id=item.id, state="pending", due_at=due)
        _adopt_existing_release(db, cohort, sv, item, row)
        db.add(row)
    audit.record(
        db,
        actor_id=actor_id,
        action="scenario.activate",
        entity_type="scenario_version",
        entity_id=sv.id,
        cohort_id=cohort.id,
        details={"case": case.code, "version": sv.version_label},
    )
    db.flush()
    return current


def _adopt_existing_release(
    db: Session, cohort: Cohort, sv: ScenarioVersion, item: ReleaseItem, row: CohortReleaseItem
) -> None:
    """Record material that was already released before the plan existed (e.g. from the cohort console).

    State only: follow-on items are not fired retroactively, so nothing new reaches students on activation.
    """
    if item.item_type == "evidence_inject":
        rel = db.scalar(
            select(InjectRelease)
            .join(Inject, Inject.id == InjectRelease.inject_id)
            .where(
                InjectRelease.cohort_id == cohort.id,
                InjectRelease.withdrawn_at.is_(None),
                Inject.scenario_version_id == sv.id,
                Inject.code == item.inject_code,
            )
        )
        if rel is not None:
            row.state, row.released_at, row.released_by_id = "released", rel.released_at, rel.released_by_id
    elif item.item_type == "document_block":
        rel = db.scalar(
            select(CurriculumDocumentRelease)
            .join(CurriculumDocument, CurriculumDocument.id == CurriculumDocumentRelease.document_id)
            .where(
                CurriculumDocumentRelease.cohort_id == cohort.id,
                CurriculumDocumentRelease.state == "released",
                CurriculumDocument.release_block == item.document_block,
            )
            .limit(1)
        )
        if rel is not None:
            row.state, row.released_at, row.released_by_id = "released", rel.released_at, rel.released_by_id


def _ensure_assignments(db: Session, cohort: Cohort, case: Case) -> None:
    """One assignment per assignment template, timed from the exercise's POI block in cohort-local time."""
    have = set(db.scalars(select(Assignment.template_id).where(Assignment.cohort_id == cohort.id)))
    for template in db.scalars(select(AssignmentTemplate)):
        if template.id in have:
            continue
        exercise = db.get(Exercise, template.exercise_id)
        block = db.scalar(
            select(ScheduleBlock).where(
                ScheduleBlock.course_version_id == cohort.course_version_id,
                ScheduleBlock.ref_code == (exercise.code if exercise else None),
            )
        )
        if block is None or block.day not in DAYS:
            continue
        db.add(
            Assignment(
                cohort_id=cohort.id,
                template_id=template.id,
                case_id=case.id,
                opens_at=_local_due(cohort, block.day, block.start_time),
                due_at=_local_due(cohort, block.day, block.end_time),
                status="open",
            )
        )


# --- per-cohort control -----------------------------------------------------------------------------
@dataclass
class Row:
    state: CohortReleaseItem
    item: ReleaseItem


def cohort_rows(db: Session, cohort_id: int) -> list[Row]:
    rows = db.execute(
        select(CohortReleaseItem, ReleaseItem)
        .join(ReleaseItem, ReleaseItem.id == CohortReleaseItem.item_id)
        .where(CohortReleaseItem.cohort_id == cohort_id)
        .order_by(ReleaseItem.sequence, ReleaseItem.id)
    ).all()
    return [Row(s, i) for s, i in rows]


def _row(db: Session, cohort_id: int, item_id: int) -> Row:
    found = db.execute(
        select(CohortReleaseItem, ReleaseItem)
        .join(ReleaseItem, ReleaseItem.id == CohortReleaseItem.item_id)
        .where(CohortReleaseItem.cohort_id == cohort_id, CohortReleaseItem.item_id == item_id)
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release item not found for this cohort")
    return Row(found[0], found[1])


def _blocker(db: Session, cohort_id: int, row: Row) -> str | None:
    item = row.item
    sv = db.get(ScenarioVersion, item.scenario_version_id)
    if sv is None or sv.approval_status != "approved" or not sv.locked:
        return "The release plan is not approved"
    if item.audience == "staff":
        return "Answer keys are for staff only and are never released to students"
    if item.trigger_type == "after_item" and item.trigger_after_code:
        prereq = next((r for r in cohort_rows(db, cohort_id) if r.item.code == item.trigger_after_code), None)
        if prereq is None or prereq.state.state != "released":
            return f"Waiting for {item.trigger_after_code} to be released first"
    if item.item_type == "evidence_inject":
        inject = db.scalar(
            select(Inject).where(Inject.scenario_version_id == sv.id, Inject.code == item.inject_code)
        )
        if inject is None or inject.approval_status != "approved":
            return f"Inject {item.inject_code} has not been approved through content approval"
    if item.scored:
        inst = db.scalar(
            select(AssessmentInstrument).where(AssessmentInstrument.code == item.instrument_code)
        )
        if inst is None or inst.authorization_status != "authorized":
            return (
                f"Scored use of {item.instrument_code} is not authorized (assessment authorization "
                "workflow); release it unscored or wait for authorization"
            )
    return None


def release_inject_to_cohort(
    db: Session, cohort_id: int, inject: Inject, actor_id: int, note: str | None
) -> bool:
    """Create or re-open an inject release. Returns False if it is already active."""
    rel = db.scalar(
        select(InjectRelease).where(
            InjectRelease.cohort_id == cohort_id, InjectRelease.inject_id == inject.id
        )
    )
    if rel is not None and rel.withdrawn_at is None:
        return False
    if rel is None:
        db.add(InjectRelease(cohort_id=cohort_id, inject_id=inject.id, released_by_id=actor_id, note=note))
    else:
        rel.withdrawn_at, rel.withdrawn_reason = None, None
        rel.released_at, rel.released_by_id, rel.note = _now(), actor_id, note
    return True


def _apply_release(
    db: Session, cohort_id: int, item: ReleaseItem, actor_id: int, lesson_id: int | None
) -> dict:
    sv_id = item.scenario_version_id
    if item.item_type == "evidence_inject":
        inject = db.scalar(
            select(Inject).where(Inject.scenario_version_id == sv_id, Inject.code == item.inject_code)
        )
        assert inject is not None
        release_inject_to_cohort(db, cohort_id, inject, actor_id, f"release plan item {item.code}")
        return {"inject": item.inject_code}
    if item.item_type == "document_block":
        cohort = db.get(Cohort, cohort_id)
        assert cohort is not None
        docs = db.scalars(
            select(CurriculumDocument).where(
                CurriculumDocument.course_version_id == cohort.course_version_id,
                CurriculumDocument.release_block == item.document_block,
                CurriculumDocument.audience == "student",
                CurriculumDocument.approval_status == "approved",
                CurriculumDocument.scan_status == "clean",
            )
        )
        codes = []
        for doc in docs:
            rel = db.scalar(
                select(CurriculumDocumentRelease).where(
                    CurriculumDocumentRelease.cohort_id == cohort_id,
                    CurriculumDocumentRelease.document_id == doc.id,
                )
            )
            if rel is None:
                rel = CurriculumDocumentRelease(
                    cohort_id=cohort_id, document_id=doc.id, released_by_id=actor_id
                )
                db.add(rel)
            rel.state, rel.released_by_id, rel.trigger_lesson_id = "released", actor_id, lesson_id
            rel.released_at, rel.withdrawn_at = _now(), None
            codes.append(doc.document_code)
        return {"documents": sorted(codes)}
    return {}


def _notify(db: Session, cohort_id: int, item: ReleaseItem) -> int:
    memberships = db.scalars(
        select(CohortMembership).where(
            CohortMembership.cohort_id == cohort_id,
            CohortMembership.role == "student",
            CohortMembership.status == "active",
        )
    )
    count = 0
    for m in memberships:
        if item.audience not in ("all_students", m.pathway):
            continue
        pref = db.get(NotificationPreference, m.user_id)
        if pref and (not pref.in_app_enabled or not pref.content_release_enabled):
            continue
        label = {
            "evidence_inject": "New case evidence",
            "document_block": "New course documents",
            "challenge": "New challenge",
            "debrief": "New debrief",
        }.get(item.item_type, "New material")
        db.add(
            Notification(
                user_id=m.user_id,
                category="content_release",
                title=label,
                body=item.title,
                entity_type="release_item",
                entity_id=str(item.id),
            )
        )
        count += 1
    return count


def release(
    db: Session,
    cohort_id: int,
    item_id: int,
    actor_id: int,
    *,
    automatic: bool = False,
    lesson_id: int | None = None,
    reason: str | None = None,
    _depth: int = 0,
) -> Row:
    row = _row(db, cohort_id, item_id)
    if row.state.state == "released":
        if automatic:
            return row
        raise HTTPException(status.HTTP_409_CONFLICT, "Already released to this cohort")
    if automatic and row.state.state == "held":
        return row  # an instructor hold beats automatic triggers
    blocker = _blocker(db, cohort_id, row)
    if blocker:
        row.state.blocked_reason = blocker
        row.state.updated_at = _now()
        audit.record(
            db,
            actor_id=actor_id,
            action="release_item.blocked",
            outcome="denied",
            entity_type="release_item",
            entity_id=item_id,
            cohort_id=cohort_id,
            details={"code": row.item.code, "reason": blocker, "automatic": automatic},
        )
        if automatic:
            return row
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, blocker)
    effects = _apply_release(db, cohort_id, row.item, actor_id, lesson_id)
    now = _now()
    row.state.state, row.state.released_at, row.state.released_by_id = "released", now, actor_id
    row.state.withdrawn_at, row.state.blocked_reason, row.state.updated_at = None, None, now
    row.state.reason = reason
    notified = _notify(db, cohort_id, row.item)
    audit.record(
        db,
        actor_id=actor_id,
        action="release_item.release",
        entity_type="release_item",
        entity_id=item_id,
        cohort_id=cohort_id,
        details={
            "code": row.item.code,
            "type": row.item.item_type,
            "automatic": automatic,
            "students_notified": notified,
            **effects,
        },
    )
    db.flush()
    # Items that wait on this one open now (bounded depth guards against bad data).
    if _depth < 20:
        for dep in cohort_rows(db, cohort_id):
            if (
                dep.item.trigger_type == "after_item"
                and dep.item.trigger_after_code == row.item.code
                and dep.state.state == "pending"
            ):
                release(db, cohort_id, dep.item.id, actor_id, automatic=True, _depth=_depth + 1)
    return row


def withdraw(db: Session, cohort_id: int, item_id: int, actor_id: int, reason: str) -> Row:
    row = _row(db, cohort_id, item_id)
    if row.state.state != "released":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only released items can be withdrawn")
    item, now = row.item, _now()
    if item.item_type == "evidence_inject":
        inject = db.scalar(
            select(Inject).where(
                Inject.scenario_version_id == item.scenario_version_id, Inject.code == item.inject_code
            )
        )
        rel = db.scalar(
            select(InjectRelease).where(
                InjectRelease.cohort_id == cohort_id, InjectRelease.inject_id == (inject.id if inject else 0)
            )
        )
        if rel is not None:
            rel.withdrawn_at, rel.withdrawn_reason = now, reason
    elif item.item_type == "document_block":
        cohort = db.get(Cohort, cohort_id)
        assert cohort is not None
        doc_ids = select(CurriculumDocument.id).where(
            CurriculumDocument.course_version_id == cohort.course_version_id,
            CurriculumDocument.release_block == item.document_block,
        )
        for rel in db.scalars(
            select(CurriculumDocumentRelease).where(
                CurriculumDocumentRelease.cohort_id == cohort_id,
                CurriculumDocumentRelease.document_id.in_(doc_ids),
                CurriculumDocumentRelease.state == "released",
            )
        ):
            rel.state, rel.withdrawn_at = "withdrawn", now
    row.state.state, row.state.withdrawn_at, row.state.reason, row.state.updated_at = (
        "withdrawn",
        now,
        reason,
        now,
    )
    audit.record(
        db,
        actor_id=actor_id,
        action="release_item.withdraw",
        entity_type="release_item",
        entity_id=item_id,
        cohort_id=cohort_id,
        details={"code": item.code, "reason": reason},
    )
    db.flush()
    return row


def hold(db: Session, cohort_id: int, item_id: int, actor_id: int, reason: str | None) -> Row:
    row = _row(db, cohort_id, item_id)
    if row.state.state != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending items can be held")
    row.state.state, row.state.reason, row.state.updated_at = "held", reason, _now()
    audit.record(
        db,
        actor_id=actor_id,
        action="release_item.hold",
        entity_type="release_item",
        entity_id=item_id,
        cohort_id=cohort_id,
        details={"code": row.item.code, "reason": reason},
    )
    db.flush()
    return row


def resume(db: Session, cohort_id: int, item_id: int, actor_id: int) -> Row:
    row = _row(db, cohort_id, item_id)
    if row.state.state != "held":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only held items can be resumed")
    row.state.state, row.state.reason, row.state.updated_at = "pending", None, _now()
    audit.record(
        db,
        actor_id=actor_id,
        action="release_item.resume",
        entity_type="release_item",
        entity_id=item_id,
        cohort_id=cohort_id,
        details={"code": row.item.code},
    )
    db.flush()
    process_due(db, cohort_id)  # a resumed item whose time has passed opens right away
    return row


# --- automatic triggers ------------------------------------------------------------------------------
def process_due(db: Session, cohort_id: int | None = None) -> int:
    """Release scheduled items whose time has come. Called by the scheduler worker and on read."""
    query = (
        select(CohortReleaseItem)
        .join(ReleaseItem, ReleaseItem.id == CohortReleaseItem.item_id)
        .where(
            CohortReleaseItem.state == "pending",
            ReleaseItem.trigger_type == "scheduled",
            CohortReleaseItem.due_at <= _now(),
        )
    )
    if cohort_id is not None:
        query = query.where(CohortReleaseItem.cohort_id == cohort_id)
    count = 0
    for state in db.scalars(query).all():
        actor = db.scalar(select(CohortCase.activated_by_id).where(CohortCase.cohort_id == state.cohort_id))
        before = state.state
        release(db, state.cohort_id, state.item_id, actor, automatic=True)
        count += state.state != before
    return count


def on_lesson_transition(
    db: Session, *, cohort_id: int, module_code: str, lifecycle_state: str, lesson_id: int, actor_id: int
) -> int:
    """Lesson stage changes open (or, on withdrawal, close) the plan items gated on that module."""
    changed = 0
    for row in cohort_rows(db, cohort_id):
        item = row.item
        if item.trigger_type != "lesson_gate" or item.trigger_module_code != module_code:
            continue
        if lifecycle_state == "withdrawn" and row.state.state == "released":
            withdraw(db, cohort_id, item.id, actor_id, f"Lesson {module_code} withdrawn")
            changed += 1
        elif item.trigger_lesson_state == lifecycle_state and row.state.state == "pending":
            release(db, cohort_id, item.id, actor_id, automatic=True, lesson_id=lesson_id)
            changed += row.state.state == "released"
    return changed
