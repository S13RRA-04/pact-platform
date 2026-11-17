"""Course materials: student downloads of released documents, staff instructor materials, and module decks.

Access rules (enforced at link creation *and* again when the link is used):
- Students: documents with audience "student" that are approved, scanned clean, and currently released to a
  cohort they actively belong to. Withdrawing the release or the enrollment stops the download.
- Staff (instructor/evaluator of any cohort, Program Administrator, curriculum roles): approved, clean
  student and instructor documents; module slide decks even while still drafts (labelled as such) so
  faculty can prepare. Students see a deck only once it is approved.
Links are short-lived, bound to the requesting user, and every download is audited.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api.admin import _attachment_header
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Cohort, CurriculumDocument, CurriculumDocumentRelease, Module
from app.security.authz import STAFF_ROLES, Principal, deny, get_principal, require_csrf_header
from app.services.object_storage import ObjectStorage
from app.services.presentation_preview import preview_pptx

router = APIRouter(tags=["materials"], dependencies=[Depends(require_csrf_header)])
SALT = "course-material-download"
CURRICULUM_ROLES = {"program_admin", "curriculum_editor", "content_approver"}
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Decks repeat a running header ("PACT", "PACT / M04") as the first text on each slide.
DECK_HEADER = re.compile(r"^PACT(\s*/\s*[A-Z0-9]+)?$")


class MaterialOut(BaseModel):
    id: int
    document_code: str
    title: str
    media_type: str
    byte_size: int
    audience: str | None
    approval_status: str
    release_day: str | None
    release_block: str | None
    released_at: datetime | None
    cohort_code: str | None


class LinkOut(BaseModel):
    url: str
    expires_in: int


class DeckOut(BaseModel):
    id: int
    document_code: str
    title: str
    approval_status: str
    slide_count: int | None
    slides: list[str]


# --- access ------------------------------------------------------------------------------------------
def _is_staff(principal: Principal) -> bool:
    return bool(principal.staff_cohort_ids(STAFF_ROLES)) or bool(principal.global_roles & CURRICULUM_ROLES)


def _student_release(
    db: Session, principal: Principal, doc: CurriculumDocument
) -> CurriculumDocumentRelease | None:
    if doc.audience != "student" or doc.approval_status != "approved" or doc.scan_status != "clean":
        return None
    cohorts = [m.cohort_id for m in principal.student_memberships()]
    return db.scalar(
        select(CurriculumDocumentRelease)
        .where(
            CurriculumDocumentRelease.document_id == doc.id,
            CurriculumDocumentRelease.state == "released",
            CurriculumDocumentRelease.cohort_id.in_(cohorts or [0]),
        )
        .limit(1)
    )


def _can_download(db: Session, principal: Principal, doc: CurriculumDocument) -> bool:
    if doc.scan_status != "clean":
        return False
    if _is_staff(principal):
        is_deck = doc.media_type == PPTX and doc.module_id is not None
        return is_deck or doc.approval_status == "approved"
    if doc.media_type == PPTX and doc.module_id is not None and doc.approval_status == "approved":
        return bool(principal.student_memberships())
    return _student_release(db, principal, doc) is not None


def _out(
    doc: CurriculumDocument, release: CurriculumDocumentRelease | None = None, cohort: str | None = None
) -> MaterialOut:
    return MaterialOut(
        id=doc.id,
        document_code=doc.document_code,
        title=doc.title,
        media_type=doc.media_type,
        byte_size=doc.byte_size,
        audience=doc.audience,
        approval_status=doc.approval_status,
        release_day=doc.release_day,
        release_block=doc.release_block,
        released_at=release.released_at if release else None,
        cohort_code=cohort,
    )


# --- listings ------------------------------------------------------------------------------------------
@router.get("/api/student/materials", response_model=list[MaterialOut])
def student_materials(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    memberships = principal.student_memberships()
    if not memberships:
        raise deny(
            db,
            principal,
            action="materials.list",
            entity_type="student_portal",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason="not enrolled as a student",
        )
    cohorts = {
        c.id: c.code
        for c in db.scalars(select(Cohort).where(Cohort.id.in_([m.cohort_id for m in memberships])))
    }
    rows = db.execute(
        select(CurriculumDocument, CurriculumDocumentRelease)
        .join(CurriculumDocumentRelease, CurriculumDocumentRelease.document_id == CurriculumDocument.id)
        .where(
            CurriculumDocumentRelease.cohort_id.in_(list(cohorts)),
            CurriculumDocumentRelease.state == "released",
            CurriculumDocument.audience == "student",
            CurriculumDocument.approval_status == "approved",
            CurriculumDocument.scan_status == "clean",
        )
        .order_by(CurriculumDocumentRelease.released_at.desc(), CurriculumDocument.document_code)
    ).all()
    return [_out(d, r, cohorts[r.cohort_id]) for d, r in rows]


@router.get("/api/staff/materials", response_model=list[MaterialOut])
def staff_materials(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not _is_staff(principal):
        raise deny(
            db,
            principal,
            action="materials.staff_list",
            entity_type="staff_portal",
            entity_id="-",
            code=status.HTTP_403_FORBIDDEN,
            reason="not staff",
        )
    docs = db.scalars(
        select(CurriculumDocument)
        .where(
            CurriculumDocument.scan_status == "clean",
            CurriculumDocument.approval_status == "approved",
            CurriculumDocument.audience.in_(("student", "instructor")),
        )
        .order_by(CurriculumDocument.audience, CurriculumDocument.document_code)  # instructor-only first
    )
    return [_out(d) for d in docs]


def _slide_titles(slides: list[dict]) -> list[str]:
    """Slide titles for an outline. Lines repeated on at least half the slides are running headers/footers
    (deck code, deck title, draft banner); after those, the first line that is not an all-caps label is the
    slide's own title (decks put a small uppercase kicker above it)."""
    per_slide = [[ln.strip() for ln in str(s.get("text", "")).splitlines() if ln.strip()] for s in slides]
    counts: dict[str, int] = {}
    for lines in per_slide:
        for ln in set(lines):
            counts[ln] = counts.get(ln, 0) + 1
    boiler = {ln for ln, n in counts.items() if len(slides) > 2 and n >= len(slides) / 2}
    titles = []
    for slide, lines in zip(slides, per_slide, strict=True):
        own = [ln for ln in lines if ln not in boiler and not DECK_HEADER.match(ln)]
        title = next((ln for ln in own if not ln.isupper()), own[0] if own else str(slide.get("title", "")))
        titles.append(title)
    return titles


@router.get("/api/curriculum/modules/{code}/presentation", response_model=DeckOut | None)
def module_presentation(
    code: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """The module's slide deck: outline and status for staff; students see it only once approved."""
    doc = db.scalar(
        select(CurriculumDocument)
        .join(Module, Module.id == CurriculumDocument.module_id)
        .where(Module.code == code, CurriculumDocument.media_type == PPTX)
        .order_by(CurriculumDocument.version_number.desc())
        .limit(1)
    )
    if doc is None or not _can_download(db, principal, doc):
        return None
    slides: list[str] = []
    if _is_staff(principal):
        try:
            preview = preview_pptx(ObjectStorage(settings).open(doc.object_key).read())
            slides = _slide_titles(preview["slides"])
        except (OSError, ValueError, KeyError):
            slides = []
    return DeckOut(
        id=doc.id,
        document_code=doc.document_code,
        title=doc.title,
        approval_status=doc.approval_status,
        slide_count=doc.slide_count,
        slides=slides,
    )


# --- downloads -------------------------------------------------------------------------------------------
@router.post("/api/materials/{document_id}/download-link", response_model=LinkOut)
def download_link(
    document_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    doc = db.get(CurriculumDocument, document_id)
    if doc is None or not _can_download(db, principal, doc):
        raise deny(
            db,
            principal,
            action="material.link",
            entity_type="curriculum_document",
            entity_id=document_id,
            reason="not released to caller or not downloadable",
        )
    token = URLSafeTimedSerializer(settings.session_secret, salt=SALT).dumps({"d": doc.id, "u": principal.id})
    return LinkOut(url=f"/api/materials/download?token={token}", expires_in=settings.download_token_seconds)


@router.get("/api/materials/download")
def download(
    token: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        claims = URLSafeTimedSerializer(settings.session_secret, salt=SALT).loads(
            token, max_age=settings.download_token_seconds
        )
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_410_GONE, "Download link expired; request a new one") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid download link") from exc
    if claims.get("u") != principal.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download link belongs to another user")
    doc = db.get(CurriculumDocument, claims.get("d"))
    # Re-check at use time: a withdrawn release, ended enrollment or revoked role must stop the download.
    if doc is None or not _can_download(db, principal, doc):
        raise deny(
            db,
            principal,
            action="material.download",
            entity_type="curriculum_document",
            entity_id=claims.get("d"),
            reason="access no longer valid",
        )
    stream = ObjectStorage(settings).open(doc.object_key)
    audit.record(
        db,
        actor_id=principal.id,
        action="material.download",
        entity_type="curriculum_document",
        entity_id=doc.id,
        details={"code": doc.document_code, "version": doc.version_number},
    )
    db.commit()
    return StreamingResponse(
        stream,
        media_type=doc.media_type,
        headers={
            "Content-Disposition": _attachment_header(doc.source_filename),
            "X-Content-Type-Options": "nosniff",
        },
    )
