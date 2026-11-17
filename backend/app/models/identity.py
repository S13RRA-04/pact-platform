"""Users, roles, cohorts, enrollments and squads."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import COHORT_ROLES, GLOBAL_ROLES, STUDENT_PATHWAYS, Base, CreatedAt, one_of


class User(CreatedAt, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(256))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    is_dev_persona: Mapped[bool] = mapped_column(Boolean, default=False)
    persona_label: Mapped[str | None] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memberships: Mapped[list[CohortMembership]] = relationship(back_populates="user")


class UserRole(CreatedAt, Base):
    """Global (non-cohort) roles."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role"), one_of("role", GLOBAL_ROLES))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    user: Mapped[User] = relationship(back_populates="roles")


class Cohort(CreatedAt, Base):
    __tablename__ = "cohorts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_versions.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Chicago")
    status: Mapped[str] = mapped_column(String(16), default="active")

    memberships: Mapped[list[CohortMembership]] = relationship(back_populates="cohort")
    squads: Mapped[list[Squad]] = relationship(back_populates="cohort")


class CohortMembership(CreatedAt, Base):
    """Cohort-scoped role. Students carry their assessed pathway."""

    __tablename__ = "cohort_memberships"
    __table_args__ = (
        UniqueConstraint("cohort_id", "user_id", "role"),
        one_of("role", COHORT_ROLES),
        one_of("pathway", STUDENT_PATHWAYS),
        one_of("status", ("active", "withdrawn")),
        # Students must have an assessed pathway; staff must not.
        CheckConstraint(
            "(role = 'student' AND pathway IS NOT NULL) OR (role <> 'student' AND pathway IS NULL)",
            name="student_pathway",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    pathway: Mapped[str | None] = mapped_column(String(16))
    # Withdrawn memberships are kept (submissions and audit history reference the enrollment period)
    # but grant no access.
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")

    cohort: Mapped[Cohort] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Squad(CreatedAt, Base):
    __tablename__ = "squads"
    __table_args__ = (UniqueConstraint("cohort_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    cohort: Mapped[Cohort] = relationship(back_populates="squads")
    members: Mapped[list[SquadMember]] = relationship(back_populates="squad")


class SquadMember(CreatedAt, Base):
    __tablename__ = "squad_members"
    __table_args__ = (UniqueConstraint("squad_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    squad_id: Mapped[int] = mapped_column(ForeignKey("squads.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    squad: Mapped[Squad] = relationship(back_populates="members")
    user: Mapped[User] = relationship()
