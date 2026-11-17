"""What a cohort member is allowed to see: released evidence, provisional content, assignments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Case,
    CohortCase,
    EvidenceItem,
    Inject,
    InjectRelease,
    ScenarioVersion,
)


def provisional_content_visible() -> bool:
    """Draft lesson/template content is shown (with a banner) only in development/test."""
    return get_settings().env in ("development", "test")


def content_visible(approval_status: str) -> bool:
    return approval_status == "approved" or provisional_content_visible()


def active_cohort_case(db: Session, cohort_id: int) -> tuple[CohortCase, ScenarioVersion, Case] | None:
    row = db.execute(
        select(CohortCase, ScenarioVersion, Case)
        .join(ScenarioVersion, ScenarioVersion.id == CohortCase.scenario_version_id)
        .join(Case, Case.id == ScenarioVersion.case_id)
        .where(CohortCase.cohort_id == cohort_id)
        .order_by(CohortCase.activated_at.desc())
        .limit(1)
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def releases(db: Session, cohort_id: int) -> dict[int, InjectRelease]:
    """Active (not withdrawn) inject releases for a cohort, keyed by inject id."""
    return {
        r.inject_id: r
        for r in db.scalars(
            select(InjectRelease).where(
                InjectRelease.cohort_id == cohort_id, InjectRelease.withdrawn_at.is_(None)
            )
        )
    }


def released_evidence(db: Session, cohort_id: int) -> list[tuple[EvidenceItem, str, datetime | None]]:
    """Evidence visible to students of a cohort: baseline packet + evidence of released injects.

    Returns (item, release label, released_at).
    """
    active = active_cohort_case(db, cohort_id)
    if active is None:
        return []
    cohort_case, sv, _case = active
    rel = releases(db, cohort_id)
    items = db.scalars(
        select(EvidenceItem).where(EvidenceItem.scenario_version_id == sv.id).order_by(EvidenceItem.sequence)
    ).all()
    injects = {i.id: i for i in db.scalars(select(Inject).where(Inject.scenario_version_id == sv.id))}
    out: list[tuple[EvidenceItem, str, datetime | None]] = []
    for item in items:
        if item.inject_id is None:
            out.append((item, "baseline", cohort_case.activated_at))
        elif item.inject_id in rel:
            out.append((item, injects[item.inject_id].code, rel[item.inject_id].released_at))
    return out


def released_evidence_codes(db: Session, cohort_id: int) -> set[str]:
    return {item.code for item, _, _ in released_evidence(db, cohort_id)}
