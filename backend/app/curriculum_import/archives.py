"""Import trusted curriculum ZIP deliveries into the quarantine workflow."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CourseVersion, CurriculumDocument, DocumentScanJob, User
from app.services.object_storage import ObjectStorage

ALLOWED_SUFFIXES = {".docx", ".csv", ".md", ".txt"}
MAX_FILES = 500
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveImportResult:
    imported: int
    deduplicated: int


def _document_code(name: str) -> str:
    path = PurePosixPath(name)
    match = re.match(r"(\d{2})_", path.name)
    if match:
        return f"HBL-{match.group(1)}"
    lower = path.name.lower()
    if "instructor_scenario_master" in lower:
        return "HBL-INSTR"
    if "source_id" in lower:
        return "HBL-SRCREG"
    if "release_register" in lower:
        return "HBL-RELREG"
    if lower == "readme.md":
        return "HBL-README"
    return "HBL-STUREAD"


def _media_type(path: PurePosixPath) -> str:
    if path.suffix.lower() == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if path.suffix.lower() == ".csv":
        return "text/csv"
    return mimetypes.guess_type(path.name)[0] or "text/plain"


def _release_mapping(code: str) -> tuple[str | None, str | None]:
    if not code.startswith("HBL-") or not code[4:].isdigit():
        return None, None
    number = int(code[4:])
    if number <= 4:
        return "Mon", "Mon start"
    if number <= 8:
        return "Tue", "Tue early"
    if number == 9:
        return "Tue", "Tue after discovery"
    if number == 10:
        return "Tue", "Tue late"
    if number == 11:
        return "Wed", "Wed am"
    if number <= 14:
        return "Wed", "Wed PM after approval"
    if number == 15:
        return "Thu", "Thu"
    return "Fri", "Fri"


def import_curriculum_archives(
    db: Session, archive_paths: list[Path], course_version_id: int | None = None
) -> ArchiveImportResult:
    version = (
        db.get(CourseVersion, course_version_id)
        if course_version_id
        else db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    )
    if version is None:
        raise ValueError("No course version is available")
    storage = ObjectStorage(get_settings())
    importer = db.scalar(select(User).where(User.username == "curr.ortega"))
    if importer is None:
        raise ValueError("The curriculum import service account is unavailable")
    # Content disarm rewrites Office files after the scan, so the stored hash changes; the original upload's
    # hash is kept in provenance and matched too, or every re-import would duplicate the scanned documents.
    by_hash: dict[str, CurriculumDocument] = {}
    for item in db.scalars(
        select(CurriculumDocument).where(CurriculumDocument.course_version_id == version.id)
    ):
        by_hash[item.source_sha256] = item
        original = (item.provenance or {}).get("original_sha256")
        if original:
            by_hash[original] = item
    imported = 0
    deduplicated = 0
    for archive_path in archive_paths:
        archive_path = archive_path.resolve(strict=True)
        if archive_path.suffix.lower() != ".zip":
            raise ValueError(f"Not a ZIP archive: {archive_path}")
        with zipfile.ZipFile(archive_path) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
                raise ValueError(f"Archive exceeds safe expansion limits: {archive_path.name}")
            for entry in entries:
                member = PurePosixPath(entry.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"Unsafe archive path: {entry.filename}")
                if member.suffix.lower() not in ALLOWED_SUFFIXES:
                    raise ValueError(f"Unsupported curriculum asset: {entry.filename}")
                if entry.file_size > MAX_FILE_BYTES:
                    raise ValueError(f"Curriculum asset is too large: {entry.filename}")
                data = archive.read(entry)
                digest = hashlib.sha256(data).hexdigest()
                existing = by_hash.get(digest)
                if existing is not None:
                    code = _document_code(entry.filename)
                    release_day, release_block = _release_mapping(code)
                    audience = (
                        "instructor"
                        if member.parts[0].lower() == "instructor"
                        or (archive_path.name.endswith("Instructor_Master.zip") and len(member.parts) == 1)
                        else "student"
                    )
                    provenance = dict(existing.provenance)
                    sources = list(provenance.get("source_archives", []))
                    if archive_path.name not in sources:
                        sources.append(archive_path.name)
                    provenance["source_archives"] = sources
                    provenance["uploaded_by"] = importer.id
                    existing.provenance = provenance
                    existing.audience = existing.audience or audience
                    existing.release_day = existing.release_day or release_day
                    existing.release_block = existing.release_block or release_block
                    deduplicated += 1
                    continue
                code = _document_code(entry.filename)
                release_day, release_block = _release_mapping(code)
                quarantine_key = f"quarantine/{version.id}/{code}/{digest}{member.suffix.lower()}"
                with tempfile.NamedTemporaryFile(suffix=member.suffix, delete=False) as temp:
                    temp.write(data)
                    temp_path = Path(temp.name)
                try:
                    storage.put_file(quarantine_key, temp_path)
                finally:
                    temp_path.unlink(missing_ok=True)
                audience = (
                    "instructor"
                    if member.parts[0].lower() == "instructor"
                    or (archive_path.name.endswith("Instructor_Master.zip") and len(member.parts) == 1)
                    else "student"
                )
                document = CurriculumDocument(
                    course_version_id=version.id,
                    document_code=code,
                    title=member.stem.replace("_", " "),
                    media_type=_media_type(member),
                    source_filename=member.name,
                    source_locator=f"{archive_path.name}!/{entry.filename}",
                    object_key=quarantine_key,
                    source_sha256=digest,
                    byte_size=len(data),
                    approval_status="draft",
                    scan_status="queued",
                    scan_details={"quarantine_key": quarantine_key},
                    audience=audience,
                    release_day=release_day,
                    release_block=release_block,
                    provenance={
                        "source_archives": [archive_path.name],
                        "archive_member": entry.filename,
                        "audience": audience,
                        "uploaded_by": importer.id,
                        "original_sha256": digest,
                    },
                )
                db.add(document)
                db.flush()
                db.add(DocumentScanJob(document_id=document.id, status="queued", attempts=0))
                by_hash[digest] = document
                imported += 1
    db.commit()
    return ArchiveImportResult(imported=imported, deduplicated=deduplicated)
