"""Database-backed quarantine and notification digest workers."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.models import (
    ApprovalRequest,
    CurriculumDocument,
    DocumentScanJob,
    Notification,
    NotificationDigest,
    NotificationPreference,
    User,
)
from app.services.document_scanner import scan_and_disarm
from app.services.object_storage import ObjectStorage


def process_scan_job(db: Session, settings: Settings) -> int:
    job = db.scalar(
        select(DocumentScanJob)
        .where(DocumentScanJob.status == "queued")
        .order_by(DocumentScanJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return 0
    document = db.get(CurriculumDocument, job.document_id)
    assert document is not None
    job.status = "running"
    job.started_at = datetime.now(UTC)
    job.attempts += 1
    db.flush()
    storage = ObjectStorage(settings)
    try:
        scan = scan_and_disarm(
            storage.open(document.object_key).read(), settings, media_type=document.media_type
        )
        if not scan.clean:
            raise ValueError("Malware detected")
        digest = hashlib.sha256(scan.sanitized).hexdigest()
        suffix = Path(document.source_filename).suffix.lower()
        final_key = (
            f"curriculum/{document.course_version_id}/{document.document_code}/"
            f"v{document.version_number}-{digest}{suffix}"
        )
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(scan.sanitized)
            path = Path(temp.name)
        try:
            storage.put_file(final_key, path)
        finally:
            path.unlink(missing_ok=True)
        storage.delete(document.object_key)
        document.object_key = final_key
        document.source_sha256 = digest
        document.byte_size = len(scan.sanitized)
        document.scan_status = "clean"
        document.scan_engine = scan.engine
        document.scanned_at = datetime.now(UTC)
        document.scan_details = scan.details
        requester = int(document.provenance.get("uploaded_by", 0))
        db.add(
            ApprovalRequest(
                workflow="content",
                entity_type="curriculum_document",
                entity_id=document.id,
                entity_code=f"{document.document_code}/v{document.version_number}",
                summary=f"Approve replacement presentation {document.document_code} version {document.version_number}",
                requested_by_id=requester,
            )
        )
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        audit.record(
            db,
            actor_id=None,
            action="document.scan.clean",
            entity_type="curriculum_document",
            entity_id=document.id,
            details=scan.details,
        )
    except Exception as exc:
        document.scan_status = "rejected"
        document.scan_details = {"error": str(exc)[:1000]}
        job.status = "failed"
        job.error = str(exc)[:2000]
        job.completed_at = datetime.now(UTC)
        audit.record(
            db,
            actor_id=None,
            action="document.scan.rejected",
            entity_type="curriculum_document",
            entity_id=document.id,
            outcome="error",
            details={"reason": str(exc)[:1000]},
        )
    db.commit()
    return 1


def build_notification_digests(db: Session) -> int:
    now = datetime.now(UTC)
    count = 0
    preferences = db.scalars(
        select(NotificationPreference).where(NotificationPreference.digest_frequency.in_(("daily", "weekly")))
    )
    for preference in preferences:
        cutoff = now - timedelta(days=1 if preference.digest_frequency == "daily" else 7)
        already = {
            item
            for digest in db.scalars(
                select(NotificationDigest).where(NotificationDigest.user_id == preference.user_id)
            )
            for item in digest.notification_ids
        }
        candidates = db.scalars(
            select(Notification)
            .where(Notification.user_id == preference.user_id, Notification.created_at >= cutoff)
            .order_by(Notification.id)
        )
        items = [item for item in candidates if item.id not in already]
        if not items:
            continue
        user = db.get(User, preference.user_id)
        db.add(
            NotificationDigest(
                user_id=preference.user_id,
                frequency=preference.digest_frequency,
                notification_ids=[item.id for item in items],
                subject=f"PACT {preference.digest_frequency} notification digest",
                body="\n".join(f"- {item.title}: {item.body}" for item in items),
                status="delivered",
                delivered_at=now,
            )
        )
        audit.record(
            db,
            actor_id=None,
            action="notification.digest.delivered",
            entity_type="user",
            entity_id=preference.user_id,
            details={
                "count": len(items),
                "frequency": preference.digest_frequency,
                "recipient": user.username if user else None,
            },
        )
        count += 1
    db.commit()
    return count
