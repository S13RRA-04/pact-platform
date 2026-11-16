"""Administrative portal: curriculum catalog, import reconciliation, approvals, audit, users."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    ActionItem,
    ApprovalRequest,
    AssessmentInstrument,
    AuditEvent,
    Cohort,
    CohortMembership,
    CourseVersion,
    CurriculumDocument,
    CurriculumLink,
    DocumentScanJob,
    ImportRun,
    Inject,
    Module,
    Objective,
    QAGate,
    User,
    WorkerHeartbeat,
)
from app.models.base import utcnow
from app.schemas.common import ApprovalDecisionIn, ApprovalOut, AuditEventOut
from app.security.authz import Principal, get_principal, require_csrf_header, require_global_role
from app.services.object_storage import ObjectStorage
from app.services.presentation_preview import preview_pptx

router = APIRouter(prefix="/api/admin", tags=["admin"])

CURRICULUM_READERS = {"curriculum_editor", "content_approver", "program_admin"}
AUDIT_READERS = {"secops_admin", "program_admin"}
APPROVAL_READERS = {"curriculum_editor", "content_approver", "program_admin"}
USER_READERS = {"program_admin", "secops_admin"}

# Which global role may decide each workflow. None = no authority configured (decision blocked).
WORKFLOW_DECIDERS: dict[str, str | None] = {
    "content": "content_approver",
    "assessment_authorization": None,  # OPEN DECISION D-05: assessment authorization authority not designated
    "deployment": None,  # This prototype is never authorized for deployment
}


def _names(db: Session, ids: list[int | None]) -> dict[int, str]:
    clean = [i for i in ids if i is not None]
    return {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(clean or [0])))}


@router.get("/curriculum")
def curriculum_catalog(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_global_role(db, principal, CURRICULUM_READERS, "admin.curriculum")
    cv = db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    if cv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No curriculum imported")
    run = db.scalar(
        select(ImportRun)
        .where(ImportRun.course_version_id == cv.id, ImportRun.outcome == "imported")
        .order_by(ImportRun.id.desc())
        .limit(1)
    )

    def rows(model: Any, *order: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.course_version_id == cv.id).order_by(*order)))

    links = rows(
        CurriculumLink, CurriculumLink.link_type, CurriculumLink.from_code, CurriculumLink.source_sheet
    )
    return {
        "course_version": {
            "id": cv.id,
            "version_label": cv.version_label,
            "status": cv.status,
            "locked": cv.locked,
            "source_filename": cv.source_filename,
            "source_sha256": cv.source_sha256,
            "source_document_status": cv.source_document_status,
        },
        "modules": [
            {
                "code": m.code,
                "title": m.title,
                "teaching_mode": m.teaching_mode,
                "objectives_text": m.objectives_text,
                "required_output": m.required_output,
                "lessons": [
                    {"code": ls.code, "title": ls.title, "approval_status": ls.approval_status}
                    for ls in m.lessons
                ],
            }
            for m in rows(Module, Module.sequence)
        ],
        "objectives": [
            {
                "code": o.code,
                "pathway": o.pathway,
                "task_code": o.task_code,
                "observable_performance": o.observable_performance,
                "validation_status": o.validation_status,
            }
            for o in rows(Objective, Objective.id)
        ],
        "instruments": [
            {
                "code": i.code,
                "name": i.name,
                "mode": i.mode,
                "day": i.day,
                "approval_standard": i.approval_standard,
                "authorization_status": i.authorization_status,
            }
            for i in rows(AssessmentInstrument, AssessmentInstrument.id)
        ],
        "links": [
            {
                "source_sheet": lk.source_sheet,
                "link_type": lk.link_type,
                "from_code": lk.from_code,
                "to_code": lk.to_code,
                "source_row_ref": lk.source_row_ref,
            }
            for lk in links
        ],
        "qa_gates": [
            {
                "code": q.code,
                "fleta_ref": q.fleta_ref,
                "control_area": q.control_area,
                "accountable_role": q.accountable_role,
                "status": q.status,
            }
            for q in rows(QAGate, QAGate.id)
        ],
        "action_items": [
            {
                "code": a.code,
                "priority": a.priority,
                "action": a.action,
                "owner": a.owner,
                "gate": a.gate,
                "status": a.status,
            }
            for a in rows(ActionItem, ActionItem.id)
        ],
        "import_run": None
        if run is None
        else {
            "id": run.id,
            "created_at": run.created_at,
            "summary": run.summary,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "subject": i.subject,
                    "detail": i.detail,
                    "resolution_status": i.resolution_status,
                }
                for i in run.issues
            ],
        },
    }


@router.get("/audit-events", response_model=list[AuditEventOut])
def audit_events(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
    outcome: str | None = None,
) -> list[AuditEventOut]:
    require_global_role(db, principal, AUDIT_READERS, "admin.audit")
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    events = list(db.scalars(q))
    names = _names(db, [e.actor_id for e in events])
    return [
        AuditEventOut(
            id=e.id,
            occurred_at=e.occurred_at,
            actor=names.get(e.actor_id or 0),
            action=e.action,
            outcome=e.outcome,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            cohort_id=e.cohort_id,
            details=e.details,
        )
        for e in events
    ]


@router.get("/worker-health")
def worker_health(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_global_role(db, principal, AUDIT_READERS, "admin.worker_health")
    item = db.get(WorkerHeartbeat, "release-scheduler")
    if item is None:
        return {"status": "not_started"}
    age = int((utcnow() - item.last_heartbeat_at).total_seconds())
    return {
        "status": "healthy" if age < 120 and not item.last_error else "degraded",
        "instance_id": item.instance_id,
        "heartbeat_age_seconds": age,
        "last_success_at": item.last_success_at,
        "last_error": item.last_error,
        "processed_count": item.processed_count,
        "max_release_lag_seconds": item.max_release_lag_seconds,
    }


def _approval_out(a: ApprovalRequest, names: dict[int, str]) -> ApprovalOut:
    return ApprovalOut(
        id=a.id,
        workflow=a.workflow,
        entity_type=a.entity_type,
        entity_code=a.entity_code,
        summary=a.summary,
        status=a.status,
        requested_by=names.get(a.requested_by_id, "—"),
        requested_at=a.requested_at,
        decided_by=names.get(a.decided_by_id or 0),
        decided_at=a.decided_at,
        decision_note=a.decision_note,
    )


@router.get("/approvals", response_model=list[ApprovalOut])
def approvals(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[ApprovalOut]:
    require_global_role(db, principal, APPROVAL_READERS, "admin.approvals")
    items = list(db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.id)))
    names = _names(db, [a.requested_by_id for a in items] + [a.decided_by_id for a in items])
    return [_approval_out(a, names) for a in items]


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalOut,
    dependencies=[Depends(require_csrf_header)],
)
def decide(
    approval_id: int,
    body: ApprovalDecisionIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ApprovalOut:
    a = db.get(ApprovalRequest, approval_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    decider = WORKFLOW_DECIDERS.get(a.workflow)
    if decider is None:
        audit.record_denial(
            db,
            actor_id=principal.id,
            action="approval.decide",
            entity_type="approval_request",
            entity_id=a.id,
            details={"reason": f"no approval authority configured for {a.workflow}"},
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"No approval authority is configured for the '{a.workflow}' workflow"
        )
    require_global_role(db, principal, {decider}, "approval.decide")
    if a.requested_by_id == principal.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requesters cannot approve their own request")
    if a.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already decided")
    a.status, a.decided_by_id, a.decided_at, a.decision_note = (
        body.decision,
        principal.id,
        utcnow(),
        body.note,
    )
    if a.workflow == "content" and a.entity_type == "inject":
        inject = db.get(Inject, a.entity_id)
        if inject is not None:
            inject.approval_status = body.decision
    if a.workflow == "content" and a.entity_type == "curriculum_document":
        document = db.get(CurriculumDocument, a.entity_id)
        if document is not None:
            if body.decision == "approved" and document.scan_status != "clean":
                raise HTTPException(status.HTTP_409_CONFLICT, "Only a clean scanned document can be approved")
            document.approval_status = body.decision
    audit.record(
        db,
        actor_id=principal.id,
        action=f"approval.{body.decision}",
        entity_type=a.entity_type,
        entity_id=a.entity_id,
        details={"workflow": a.workflow, "entity_code": a.entity_code, "approval_request_id": a.id},
    )
    db.commit()
    return _approval_out(a, _names(db, [a.requested_by_id, a.decided_by_id]))


@router.post("/curriculum-documents/{document_id}/replacement", dependencies=[Depends(require_csrf_header)])
def replace_document(
    document_id: int,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_global_role(db, principal, {"curriculum_editor", "program_admin"}, "document.replace")
    current = db.get(CurriculumDocument, document_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A PPTX file is required")
    data = file.file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Document exceeds 100 MB")
    digest = hashlib.sha256(data).hexdigest()
    version = current.version_number + 1
    key = f"quarantine/{current.course_version_id}/{current.document_code}/v{version}-{digest}.pptx"
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as temp:
        temp.write(data)
        temp_path = Path(temp.name)
    try:
        ObjectStorage(settings).put_file(key, temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    replacement = CurriculumDocument(
        course_version_id=current.course_version_id,
        module_id=current.module_id,
        replaces_document_id=current.id,
        version_number=version,
        document_code=current.document_code,
        title=current.title,
        media_type=current.media_type,
        source_filename=file.filename,
        source_locator="uploaded",
        object_key=key,
        source_sha256=digest,
        byte_size=len(data),
        slide_count=None,
        approval_status="draft",
        scan_status="queued",
        scan_engine=None,
        scanned_at=None,
        scan_details={"quarantine_key": key},
        provenance={"uploaded_by": principal.id},
    )
    db.add(replacement)
    db.flush()
    job = DocumentScanJob(document_id=replacement.id)
    db.add(job)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="document.replacement.quarantined",
        entity_type="curriculum_document",
        entity_id=replacement.id,
        details={"replaces": current.id, "sha256": digest, "object_key": key},
    )
    db.commit()
    return {
        "document_id": replacement.id,
        "version_number": version,
        "scan_job_id": job.id,
        "scan_status": "queued",
    }


@router.post("/curriculum-documents/{document_id}/download-link", dependencies=[Depends(require_csrf_header)])
def document_download_link(
    document_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_global_role(db, principal, CURRICULUM_READERS, "document.download")
    document = db.get(CurriculumDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    token = URLSafeTimedSerializer(settings.session_secret, salt="document-download").dumps(
        {"document_id": document.id, "user_id": principal.id}
    )
    return {
        "url": f"/api/admin/curriculum-documents/download?token={token}",
        "expires_in": settings.download_token_seconds,
    }


@router.get("/curriculum-documents/{document_id}/preview")
def document_preview(
    document_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_global_role(db, principal, CURRICULUM_READERS, "document.preview")
    document = db.get(CurriculumDocument, document_id)
    if document is None or document.scan_status != "clean":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only clean documents can be previewed")
    preview = preview_pptx(ObjectStorage(settings).open(document.object_key).read())
    return {
        "document_id": document.id,
        "document_code": document.document_code,
        "version_number": document.version_number,
        "source_filename": document.source_filename,
        "byte_size": document.byte_size,
        "source_sha256": document.source_sha256,
        **preview,
    }


@router.post("/curriculum-documents/{document_id}/retire", dependencies=[Depends(require_csrf_header)])
def retire_document(
    document_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
):
    require_global_role(db, principal, {"content_approver", "program_admin"}, "document.retire")
    document = db.get(CurriculumDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if document.approval_status == "retired":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document already retired")
    document.approval_status = "retired"
    audit.record(
        db,
        actor_id=principal.id,
        action="document.retire",
        entity_type="curriculum_document",
        entity_id=document.id,
        details={"document_code": document.document_code, "version": document.version_number},
    )
    db.commit()
    return {"status": "retired", "document_id": document.id}


@router.get("/curriculum-documents/download")
def download_document(
    token: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        claims = URLSafeTimedSerializer(settings.session_secret, salt="document-download").loads(
            token, max_age=settings.download_token_seconds
        )
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_410_GONE, "Download link expired") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid download link") from exc
    if claims.get("user_id") != principal.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download link belongs to another user")
    document = db.get(CurriculumDocument, claims.get("document_id"))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    stream = ObjectStorage(settings).open(document.object_key)
    audit.record(
        db,
        actor_id=principal.id,
        action="document.download",
        entity_type="curriculum_document",
        entity_id=document.id,
        details={"version": document.version_number},
    )
    db.commit()
    return StreamingResponse(
        stream,
        media_type=document.media_type,
        headers={"Content-Disposition": f'attachment; filename="{document.source_filename}"'},
    )


@router.get("/users")
def users(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_global_role(db, principal, USER_READERS, "admin.users")
    cohorts = {c.id: c.code for c in db.scalars(select(Cohort))}
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        ms = db.scalars(select(CohortMembership).where(CohortMembership.user_id == u.id))
        out.append(
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "is_synthetic": u.is_synthetic,
                "is_dev_persona": u.is_dev_persona,
                "active": u.active,
                "global_roles": sorted(r.role for r in u.roles),
                "cohort_roles": [
                    {"cohort": cohorts[m.cohort_id], "role": m.role, "pathway": m.pathway} for m in ms
                ],
            }
        )
    return out
