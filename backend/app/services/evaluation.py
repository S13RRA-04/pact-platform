"""Provisional evaluator feedback. Every save appends a new revision; nothing is overwritten."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import audit
from app.models import (
    Assignment,
    AssignmentTemplate,
    Cohort,
    CriterionResult,
    EvaluationRecord,
    FeedbackRelease,
    Objective,
    ObjectiveEvidenceNote,
    RubricCriterion,
    Submission,
    User,
)
from app.schemas.common import (
    CriterionResultOut,
    EvaluationIn,
    EvaluationRecordOut,
    ObjectiveNoteOut,
    ObjectiveStatusOut,
)
from app.security.authz import Principal
from app.services.competency import NOT_DETERMINED_REASON
from app.services.work import instrument_objective_codes


def submission_context(db: Session, sub: Submission) -> tuple[Assignment, AssignmentTemplate, Cohort]:
    assignment = db.get(Assignment, sub.assignment_id)
    assert assignment is not None
    template = db.get(AssignmentTemplate, assignment.template_id)
    cohort = db.get(Cohort, sub.cohort_id)
    assert template is not None and cohort is not None
    return assignment, template, cohort


def criteria_for(db: Session, template: AssignmentTemplate) -> list[RubricCriterion]:
    return list(
        db.scalars(
            select(RubricCriterion)
            .where(
                RubricCriterion.instrument_id == template.instrument_id,
                RubricCriterion.pathway.in_(("common", template.pathway)),
            )
            .order_by(RubricCriterion.sequence)
        )
    )


def objectives_in_scope(
    db: Session, cohort: Cohort, template: AssignmentTemplate, instrument_code: str
) -> list[Objective]:
    """Instrument objectives (Assessments sheet) applicable to the student's pathway (common + own pathway)."""
    codes = instrument_objective_codes(db, cohort.course_version_id, instrument_code)
    objs = db.scalars(
        select(Objective)
        .where(Objective.course_version_id == cohort.course_version_id, Objective.code.in_(codes))
        .order_by(Objective.code)
    )
    return [o for o in objs if o.pathway in ("common", "integrated", template.pathway)]


def record_evaluation(
    db: Session, principal: Principal, sub: Submission, payload: EvaluationIn, instrument_code: str
) -> EvaluationRecord:
    _, template, cohort = submission_context(db, sub)
    criteria = {c.id: c for c in criteria_for(db, template)}
    objectives = {o.code: o for o in objectives_in_scope(db, cohort, template, instrument_code)}
    for cr in payload.criterion_results:
        if cr.criterion_id not in criteria:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Criterion {cr.criterion_id} not in rubric"
            )
    if len({cr.criterion_id for cr in payload.criterion_results}) != len(payload.criterion_results):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate criterion result")
    for on in payload.objective_notes:
        if on.objective_code not in objectives:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Objective {on.objective_code} is not evaluated by this instrument for this pathway",
            )
    if not (payload.criterion_results or payload.objective_notes or payload.summary_comment.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Feedback is empty")

    # Serialize revisions per submission.
    db.execute(select(Submission.id).where(Submission.id == sub.id).with_for_update())
    current = db.scalar(
        select(func.max(EvaluationRecord.revision)).where(EvaluationRecord.submission_id == sub.id)
    )
    record = EvaluationRecord(
        submission_id=sub.id,
        evaluator_id=principal.id,
        revision=(current or 0) + 1,
        status="provisional",
        summary_comment=payload.summary_comment,
        remediation_note=payload.remediation_note,
    )
    db.add(record)
    db.flush()
    for cr in payload.criterion_results:
        db.add(
            CriterionResult(
                evaluation_record_id=record.id,
                criterion_id=cr.criterion_id,
                observation=cr.observation,
                comment=cr.comment,
                evidence_refs=list(dict.fromkeys(cr.evidence_refs)),
            )
        )
    for on in payload.objective_notes:
        db.add(
            ObjectiveEvidenceNote(
                evaluation_record_id=record.id, objective_id=objectives[on.objective_code].id, note=on.note
            )
        )
    audit.record(
        db,
        actor_id=principal.id,
        action="evaluation.record",
        entity_type="evaluation_record",
        entity_id=record.id,
        cohort_id=sub.cohort_id,
        details={"submission_id": sub.id, "revision": record.revision, "status": "provisional"},
    )
    db.flush()
    return record


def release_feedback(
    db: Session, principal: Principal, record: EvaluationRecord, cohort_id: int
) -> FeedbackRelease:
    if db.scalar(select(FeedbackRelease.id).where(FeedbackRelease.evaluation_record_id == record.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Feedback revision already released")
    _, template, _ = submission_context(db, db.get(Submission, record.submission_id))  # type: ignore[arg-type]
    expected = {c.id for c in criteria_for(db, template)}
    recorded = {r.criterion_id: r for r in record.criterion_results}
    incomplete = [
        criterion_id
        for criterion_id in expected
        if criterion_id not in recorded or recorded[criterion_id].observation == "not_assessed"
    ]
    if incomplete:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Rubric is incomplete; assess criteria: {', '.join(map(str, sorted(incomplete)))}",
        )
    if not record.summary_comment.strip():
        raise HTTPException(status.HTTP_409_CONFLICT, "A summary comment is required before release")
    rel = FeedbackRelease(evaluation_record_id=record.id, released_by_id=principal.id)
    db.add(rel)
    audit.record(
        db,
        actor_id=principal.id,
        action="feedback.release",
        entity_type="evaluation_record",
        entity_id=record.id,
        cohort_id=cohort_id,
        details={"submission_id": record.submission_id, "revision": record.revision},
    )
    db.flush()
    return rel


def rubric_complete(db: Session, record: EvaluationRecord) -> bool:
    sub = db.get(Submission, record.submission_id)
    if sub is None:
        return False
    _, template, _ = submission_context(db, sub)
    expected = {c.id for c in criteria_for(db, template)}
    recorded = {r.criterion_id: r.observation for r in record.criterion_results}
    return bool(expected) and all(
        recorded.get(criterion_id) not in (None, "not_assessed") for criterion_id in expected
    )


def evaluation_history(
    db: Session, submission_id: int, released_only: bool = False
) -> list[EvaluationRecordOut]:
    records = db.scalars(
        select(EvaluationRecord)
        .where(EvaluationRecord.submission_id == submission_id)
        .options(
            selectinload(EvaluationRecord.criterion_results), selectinload(EvaluationRecord.objective_notes)
        )
        .order_by(EvaluationRecord.revision)
    ).all()
    releases = {
        r.evaluation_record_id: r
        for r in db.scalars(
            select(FeedbackRelease).where(
                FeedbackRelease.evaluation_record_id.in_([r.id for r in records] or [0])
            )
        )
    }
    crit = {c.id: c for c in db.scalars(select(RubricCriterion))}
    obj = {
        o.id: o.code
        for o in db.scalars(
            select(Objective).where(
                Objective.id.in_([n.objective_id for r in records for n in r.objective_notes] or [0])
            )
        )
    }
    out = []
    for r in records:
        rel = releases.get(r.id)
        if released_only and rel is None:
            continue
        evaluator = db.get(User, r.evaluator_id)
        out.append(
            EvaluationRecordOut(
                id=r.id,
                revision=r.revision,
                status=r.status,
                evaluator_name=evaluator.display_name if evaluator else "—",
                created_at=r.created_at,
                summary_comment=r.summary_comment,
                remediation_note=r.remediation_note,
                criterion_results=[
                    CriterionResultOut(
                        criterion_id=c.criterion_id,
                        criterion_code=crit[c.criterion_id].code,
                        criterion_title=crit[c.criterion_id].title,
                        observation=c.observation,
                        comment=c.comment,
                        evidence_refs=list(c.evidence_refs),
                    )
                    for c in r.criterion_results
                ],
                objective_notes=[
                    ObjectiveNoteOut(objective_code=obj[n.objective_id], note=n.note)
                    for n in r.objective_notes
                ],
                released=rel is not None,
                released_at=rel.released_at if rel else None,
            )
        )
    return out


def objective_status(
    objectives: list[Objective], feedback: EvaluationRecordOut | None
) -> list[ObjectiveStatusOut]:
    notes: dict[str, list[str]] = {}
    if feedback:
        for n in feedback.objective_notes:
            notes.setdefault(n.objective_code, []).append(n.note)
    return [
        ObjectiveStatusOut(
            objective_code=o.code,
            pathway=o.pathway,
            observable_performance=o.observable_performance,
            evidence_notes=notes.get(o.code, []),
            determination="not_determined",
            determination_reason=NOT_DETERMINED_REASON,
        )
        for o in objectives
    ]
