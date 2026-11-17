"""Connect approved document gates to cohort lesson lifecycle transitions."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import CurriculumDocument, CurriculumDocumentRelease

GATE_TRIGGERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("M01", "released"): ("Mon start",),
    ("M04", "released"): ("Tue early",),
    ("M04", "taught"): ("Tue after discovery",),
    ("M05", "taught"): ("Tue late",),
    ("M06", "released"): ("Wed am",),
    ("M06", "taught"): ("Wed PM after approval",),
    ("M08", "released"): ("Thu",),
    ("M10", "released"): ("Fri",),
}


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
    now = datetime.now(UTC)
    if lifecycle_state == "withdrawn":
        rows = list(
            db.scalars(
                select(CurriculumDocumentRelease).where(
                    CurriculumDocumentRelease.cohort_id == cohort_id,
                    CurriculumDocumentRelease.trigger_lesson_id == lesson_id,
                    CurriculumDocumentRelease.state == "released",
                )
            )
        )
        for row in rows:
            row.state = "withdrawn"
            row.withdrawn_at = now
        return len(rows)
    gates = GATE_TRIGGERS.get((module_code, lifecycle_state), ())
    if not gates:
        return 0
    documents = db.scalars(
        select(CurriculumDocument).where(
            CurriculumDocument.course_version_id == course_version_id,
            CurriculumDocument.release_block.in_(gates),
            CurriculumDocument.audience == "student",
            CurriculumDocument.approval_status == "approved",
            CurriculumDocument.scan_status == "clean",
        )
    )
    changed = 0
    for document in documents:
        release = db.scalar(
            select(CurriculumDocumentRelease).where(
                CurriculumDocumentRelease.cohort_id == cohort_id,
                CurriculumDocumentRelease.document_id == document.id,
            )
        )
        if release is None:
            release = CurriculumDocumentRelease(
                cohort_id=cohort_id,
                document_id=document.id,
                released_by_id=actor_id,
                trigger_lesson_id=lesson_id,
            )
            db.add(release)
        release.state = "released"
        release.released_by_id = actor_id
        release.trigger_lesson_id = lesson_id
        release.released_at = now
        release.withdrawn_at = None
        changed += 1
    if changed:
        audit.record(
            db,
            actor_id=actor_id,
            action="curriculum_documents.released",
            entity_type="lesson",
            entity_id=lesson_id,
            cohort_id=cohort_id,
            details={"module_code": module_code, "lifecycle_state": lifecycle_state, "count": changed},
        )
    return changed
