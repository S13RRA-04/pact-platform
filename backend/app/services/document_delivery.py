"""Lesson lifecycle → release plan bridge.

Which material opens at which lesson stage used to be a hard-coded table here (GATE_TRIGGERS). It is now
data: release-plan items with a "lesson_gate" trigger, approved as part of the scenario's release plan and
editable by curriculum staff (see app/services/release_plan.py). This function keeps its original
signature so the lesson endpoints and the scheduler call it unchanged.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CurriculumDocumentRelease
from app.services import release_plan


def apply_document_gate(
    db: Session,
    *,
    cohort_id: int,
    course_version_id: int,
    module_code: str,
    lifecycle_state: str,
    lesson_id: int,
    actor_id: int,
) -> int:
    changed = release_plan.on_lesson_transition(
        db,
        cohort_id=cohort_id,
        module_code=module_code,
        lifecycle_state=lifecycle_state,
        lesson_id=lesson_id,
        actor_id=actor_id,
    )
    if lifecycle_state == "withdrawn":
        # Also close any document released by this specific lesson outside a plan item.
        for row in db.scalars(
            select(CurriculumDocumentRelease).where(
                CurriculumDocumentRelease.cohort_id == cohort_id,
                CurriculumDocumentRelease.trigger_lesson_id == lesson_id,
                CurriculumDocumentRelease.state == "released",
            )
        ):
            row.state = "withdrawn"
            row.withdrawn_at = datetime.now(UTC)
            changed += 1
    return changed
