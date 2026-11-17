"""Server-side authorization.

Conventions:
- 401: no valid session.
- 403: authenticated but lacks the role for an action (e.g. a student calling a staff endpoint).
- 404: the object exists outside the caller's visibility (other cohort, other student's work,
  unreleased evidence). Returning 404 avoids confirming that hidden objects exist.
All denials on protected resources are written to the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import record_denial
from app.config import Settings, get_settings
from app.db import get_db
from app.models import CohortMembership, User
from app.security import session as sess

STAFF_ROLES = frozenset({"instructor", "evaluator"})


@dataclass
class Principal:
    user: User
    global_roles: frozenset[str]
    memberships: list[CohortMembership] = field(default_factory=list)
    session_id: int | None = None

    @property
    def id(self) -> int:
        return self.user.id

    def cohort_roles(self, cohort_id: int) -> set[str]:
        return {m.role for m in self.memberships if m.cohort_id == cohort_id}

    def student_membership(self, cohort_id: int) -> CohortMembership | None:
        return next((m for m in self.memberships if m.cohort_id == cohort_id and m.role == "student"), None)

    def student_memberships(self) -> list[CohortMembership]:
        return [m for m in self.memberships if m.role == "student"]

    def staff_cohort_ids(self, roles: frozenset[str] = STAFF_ROLES) -> list[int]:
        return sorted({m.cohort_id for m in self.memberships if m.role in roles})


def get_principal(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> Principal:
    record = sess.lookup(db, request, settings)
    # A session still waiting for its second factor authorizes nothing.
    if record is None or not record.mfa_verified:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    user = db.scalar(
        select(User).where(User.id == record.user_id, User.active.is_(True)).options(selectinload(User.roles))
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    if user.is_dev_persona and not settings.dev_personas_enabled:
        # A persona session must never be honored outside development (fail closed).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    memberships = list(
        db.scalars(
            select(CohortMembership).where(
                CohortMembership.user_id == user.id, CohortMembership.status == "active"
            )
        ).all()
    )
    return Principal(user, frozenset(r.role for r in user.roles), memberships, session_id=record.id)


def require_csrf_header(request: Request) -> None:
    """Mutating requests must carry a custom header (blocks simple cross-site form posts)."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(sess.CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing request header")


def deny(
    db: Session,
    principal: Principal,
    *,
    action: str,
    entity_type: str,
    entity_id: object,
    cohort_id: int | None = None,
    code: int = status.HTTP_404_NOT_FOUND,
    reason: str = "",
) -> HTTPException:
    record_denial(
        db,
        actor_id=principal.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        cohort_id=cohort_id,
        details={"reason": reason} if reason else None,
    )
    return HTTPException(code, "Not found" if code == status.HTTP_404_NOT_FOUND else "Forbidden")


def require_cohort_role(
    db: Session, principal: Principal, cohort_id: int, roles: frozenset[str] | set[str], action: str
) -> None:
    held = principal.cohort_roles(cohort_id)
    if not held & set(roles):
        # Not a member at all -> hide the cohort (404). Member with the wrong role -> 403.
        raise deny(
            db,
            principal,
            action=action,
            entity_type="cohort",
            entity_id=cohort_id,
            cohort_id=cohort_id,
            code=status.HTTP_403_FORBIDDEN if held else status.HTTP_404_NOT_FOUND,
            reason=f"requires one of {sorted(roles)}",
        )


def require_global_role(db: Session, principal: Principal, roles: set[str], action: str) -> None:
    if not principal.global_roles & roles:
        raise deny(
            db,
            principal,
            action=action,
            entity_type="global",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason=f"requires one of {sorted(roles)}",
        )
