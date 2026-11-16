from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    cohort_id: int | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (committed with the business change)."""
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        cohort_id=cohort_id,
        details=details or {},
    )
    db.add(event)
    return event


def record_denial(db: Session, **kwargs: Any) -> None:
    """Denials are committed immediately, independent of the (aborted) request transaction."""
    db.rollback()
    record(db, outcome="denied", **kwargs)
    db.commit()
