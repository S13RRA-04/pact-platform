from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def one_of(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name or f"{column}_valid")


# Shared vocabularies -------------------------------------------------------
PATHWAYS = ("common", "investigator", "analyst", "integrated")
STUDENT_PATHWAYS = ("investigator", "analyst")
COHORT_ROLES = ("student", "instructor", "evaluator")
GLOBAL_ROLES = ("curriculum_editor", "content_approver", "program_admin", "secops_admin")
APPROVAL_STATUSES = ("draft", "pending", "approved", "rejected", "retired")
