"""Import PPTX manifest entries as controlled metadata records.

The source locator is backend-only. This command does not publish or serve document bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CourseVersion, CurriculumDocument, Module
from app.models.base import utcnow
from app.services.object_storage import ObjectStorage


def import_presentations(db: Session, suite_dir: Path, course_version_id: int | None = None) -> int:
    manifest_path = suite_dir / "manifest.json"
    presentation_dir = suite_dir / "Presentations"
    entries = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    version = (
        db.get(CourseVersion, course_version_id)
        if course_version_id
        else db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    )
    if version is None:
        raise ValueError("No course version is available")
    modules = {
        module.code: module
        for module in db.scalars(select(Module).where(Module.course_version_id == version.id))
    }
    imported = 0
    storage = ObjectStorage(get_settings())
    for entry in entries:
        path = (presentation_dir / entry["file"]).resolve(strict=True)
        if path.suffix.lower() != ".pptx" or presentation_dir.resolve() not in path.parents:
            raise ValueError(f"Invalid presentation path: {entry['file']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        object_key = f"curriculum/{version.id}/{entry['id']}/{digest}.pptx"
        storage.put_file(object_key, path)
        document = db.scalar(
            select(CurriculumDocument).where(
                CurriculumDocument.course_version_id == version.id,
                CurriculumDocument.document_code == entry["id"],
            )
        )
        if document is None:
            document = CurriculumDocument(course_version_id=version.id, document_code=entry["id"])
            db.add(document)
        document.module_id = modules.get(entry["id"]).id if entry["id"] in modules else None
        document.title = entry["module"]
        document.media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        document.source_filename = path.name
        document.source_locator = str(path)
        document.object_key = object_key
        document.source_sha256 = digest
        document.byte_size = path.stat().st_size
        document.slide_count = entry.get("slides")
        document.approval_status = "draft"
        document.scan_status = "clean"
        document.scan_engine = "trusted-admin-import"
        document.scanned_at = utcnow()
        document.scan_details = {"source": "controlled curriculum import"}
        document.provenance = {
            "manifest": manifest_path.name,
            "objectives": entry.get("objectives", []),
            "duration": entry.get("duration"),
        }
        imported += 1
    db.commit()
    return imported
