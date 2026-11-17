"""Server-owned lesson lifecycle and scheduled opening rules."""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import audit
from app.models import (
    Cohort,
    CohortMembership,
    Lesson,
    LessonRelease,
    Module,
    Notification,
    NotificationPreference,
)
from app.services.document_delivery import apply_document_gate


def open_due_releases(db: Session, cohort_id: int | None = None) -> int:
    now = datetime.now(UTC)
    if db.bind and db.bind.dialect.name == "postgresql":
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(70616374)")):
            return 0
    query = select(LessonRelease).where(
        LessonRelease.state == "scheduled",
        LessonRelease.scheduled_for <= now,
    )
    if cohort_id is not None:
        query = query.where(LessonRelease.cohort_id == cohort_id)
    due = db.scalars(query.with_for_update(skip_locked=True)).all()
    for release in due:
        release.state = "released"
        release.released_at = now
        audit.record(
            db,
            actor_id=release.released_by_id,
            action="lesson.release.automatic",
            entity_type="lesson",
            entity_id=release.lesson_id,
            cohort_id=release.cohort_id,
            details={"scheduled_for": release.scheduled_for.isoformat() if release.scheduled_for else None},
        )
        lesson = db.get(Lesson, release.lesson_id)
        module = db.get(Module, lesson.module_id) if lesson else None
        cohort = db.get(Cohort, release.cohort_id)
        if lesson and module and cohort:
            apply_document_gate(
                db,
                cohort_id=cohort.id,
                course_version_id=cohort.course_version_id,
                module_code=module.code,
                lifecycle_state="released",
                lesson_id=lesson.id,
                actor_id=release.released_by_id,
            )
        student_ids = db.scalars(
            select(CohortMembership.user_id).where(
                CohortMembership.cohort_id == release.cohort_id,
                CohortMembership.role == "student",
                CohortMembership.status == "active",
            )
        )
        for user_id in student_ids:
            preference = db.get(NotificationPreference, user_id)
            if preference and (not preference.in_app_enabled or not preference.content_release_enabled):
                continue
            db.add(
                Notification(
                    user_id=user_id,
                    category="content_release",
                    title="New lesson available",
                    body=lesson.title if lesson else "New course content is available",
                    entity_type="lesson",
                    entity_id=str(release.lesson_id),
                )
            )
    if due:
        db.commit()
    return len(due)


def visible_lesson_ids(db: Session, cohort_id: int) -> set[int]:
    open_due_releases(db, cohort_id)
    return set(
        db.scalars(
            select(LessonRelease.lesson_id).where(
                LessonRelease.cohort_id == cohort_id,
                LessonRelease.state == "released",
            )
        )
    )
