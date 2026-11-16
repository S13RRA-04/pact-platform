"""Competency determinations.

No standard of competence has been approved (QA gate Q12, Action Register B05). This module is the
single place a determination could be made, and it refuses unless an *approved* ``CompetencyRule``
exists for the objective. Attendance, lesson completion, quiz percentages, team performance and
provisional rubric observations are never inputs to a determination.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompetencyRule, ObjectiveDetermination

NOT_DETERMINED_REASON = (
    "No approved standard of competence exists for this objective (QA gate Q12 / Action Register B05). "
    "Provisional rubric observations are formative feedback, not a determination."
)


class CompetencyRuleMissing(Exception):
    pass


def approved_rule(db: Session, objective_id: int) -> CompetencyRule | None:
    return db.scalar(
        select(CompetencyRule).where(
            CompetencyRule.objective_id == objective_id, CompetencyRule.approval_status == "approved"
        )
    )


def record_determination(
    db: Session,
    *,
    cohort_id: int,
    student_id: int,
    objective_id: int,
    determination: str,
    determined_by_id: int,
) -> ObjectiveDetermination:
    rule = approved_rule(db, objective_id)
    if rule is None:
        raise CompetencyRuleMissing(NOT_DETERMINED_REASON)
    record = ObjectiveDetermination(
        cohort_id=cohort_id,
        student_id=student_id,
        objective_id=objective_id,
        rule_id=rule.id,
        determination=determination,
        determined_by_id=determined_by_id,
    )
    db.add(record)
    return record
