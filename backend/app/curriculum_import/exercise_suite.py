"""Import the HARBORLINE v0.3 reinforcing exercise suite (directory delivery) into controlled documents.

Every file goes through the same quarantine → scan → approval path as other curriculum uploads.
Audience follows the faculty release plan in the suite:
- Student exercise packets and the student workbook are student material (released per exercise).
- The instructor master, annotated key, development knowledge checks, objective register, faculty release
  plan, objective map, READMEs and the *complete* source dossier are instructor-only
  ("Do not distribute the instructor master archive or complete source dossier to students").
- The staged Day 1–4 case-record files are not imported as documents; they become the case's evidence
  library (see app/seed/harborline.py), released record by record.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CourseVersion, CurriculumDocument, DocumentScanJob, User
from app.services.object_storage import ObjectStorage

MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".md": "text/markdown",
    ".json": "application/json",
}
MAX_FILE_BYTES = 25 * 1024 * 1024
PACKET_RE = re.compile(r"^(E\d{2}|EPROV|P05)_Student_Packet\.docx$")
INSTRUCTOR_CODES = {
    "PACT_HARBORLINE_Instructor_Master_v0.3.docx": "HBL3-MASTER",
    "PACT_HARBORLINE_Annotated_Instructor_Key_v0.3.docx": "HBL3-KEY",
    "PACT_Development_Knowledge_Checks_v0.3.docx": "HBL3-KC",
    "PACT_Objective_Assessment_Register_v0.3.xlsx": "HBL3-REGISTER",
    "FACULTY_RELEASE_PLAN.md": "HBL3-FACULTY",
    "objective_map.json": "HBL3-OBJMAP",
    "HARBORLINE_Source_Dossier_v0.3.docx": "HBL3-DOSSIER",
}


@dataclass(frozen=True)
class SuiteFile:
    path: Path
    code: str
    audience: str


@dataclass
class SuiteImportResult:
    imported: list[int]
    unchanged: int


def docx_text(path: Path) -> str:
    """Plain text of a .docx (paragraphs and table cells), used for titles and answer-key extraction."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:tc>", " | ", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    text = unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def suite_files(instructor_dir: Path) -> list[SuiteFile]:
    """Files to import from the instructor master delivery (a superset of the student delivery)."""
    files: list[SuiteFile] = []
    student = instructor_dir / "Student"
    for path in sorted(student.glob("*_Student_Packet.docx")):
        match = PACKET_RE.match(path.name)
        if match:
            files.append(SuiteFile(path, f"PKT-{match.group(1)}", "student"))
    workbook = student / "PACT_HARBORLINE_Student_Workbook_v0.3.docx"
    if workbook.exists():
        files.append(SuiteFile(workbook, "HBL3-WORKBOOK", "student"))
    for name, code in INSTRUCTOR_CODES.items():
        for candidate in (instructor_dir / "Instructor" / name, student / name, instructor_dir / name):
            if candidate.exists():
                files.append(SuiteFile(candidate, code, "instructor"))
                break
    readme = instructor_dir / "README.md"
    if readme.exists():
        files.append(SuiteFile(readme, "HBL3-README", "instructor"))
    return files


def _title(file: SuiteFile) -> str:
    if file.path.suffix == ".docx":
        first = next((ln.strip() for ln in docx_text(file.path).splitlines() if ln.strip()), "")
        if first:
            return re.sub(r"\s*\|\s*", " — ", first)[:250]
    return file.path.stem.replace("_", " ")


def import_exercise_suite(
    db: Session, instructor_dir: Path, course_version_id: int | None = None
) -> SuiteImportResult:
    instructor_dir = instructor_dir.resolve(strict=True)
    version = (
        db.get(CourseVersion, course_version_id)
        if course_version_id
        else db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    )
    if version is None:
        raise ValueError("No course version is available")
    importer = db.scalar(select(User).where(User.username == "curr.ortega"))
    if importer is None:
        raise ValueError("The curriculum import service account is unavailable")
    storage = ObjectStorage(get_settings())
    imported: list[int] = []
    unchanged = 0
    for file in suite_files(instructor_dir):
        if file.path.suffix.lower() not in MEDIA_TYPES:
            raise ValueError(f"Unsupported curriculum asset: {file.path.name}")
        data = file.path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"Curriculum asset is too large: {file.path.name}")
        digest = hashlib.sha256(data).hexdigest()
        # Scanning disarms Office files and stores the *sanitized* hash, so also match the original upload hash
        # kept in provenance; otherwise every re-import would look like new content.
        if db.scalar(
            select(CurriculumDocument.id).where(
                CurriculumDocument.course_version_id == version.id,
                (CurriculumDocument.source_sha256 == digest)
                | (CurriculumDocument.provenance["original_sha256"].as_string() == digest),
            )
        ):
            unchanged += 1
            continue
        latest = db.scalar(
            select(func.max(CurriculumDocument.version_number)).where(
                CurriculumDocument.course_version_id == version.id,
                CurriculumDocument.document_code == file.code,
            )
        )
        quarantine_key = f"quarantine/{version.id}/{file.code}/{digest}{file.path.suffix.lower()}"
        with tempfile.NamedTemporaryFile(suffix=file.path.suffix, delete=False) as temp:
            temp.write(data)
            temp_path = Path(temp.name)
        try:
            storage.put_file(quarantine_key, temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        document = CurriculumDocument(
            course_version_id=version.id,
            document_code=file.code,
            version_number=(latest or 0) + 1,
            title=_title(file),
            media_type=MEDIA_TYPES[file.path.suffix.lower()],
            source_filename=file.path.name,
            source_locator=str(file.path.relative_to(instructor_dir.parent)),
            object_key=quarantine_key,
            source_sha256=digest,
            byte_size=len(data),
            approval_status="draft",
            scan_status="queued",
            scan_details={"quarantine_key": quarantine_key},
            audience=file.audience,
            provenance={
                "suite": "HARBORLINE v0.3 reinforcing exercise suite",
                "audience": file.audience,
                "uploaded_by": importer.id,
                "original_sha256": digest,
            },
        )
        db.add(document)
        db.flush()
        db.add(DocumentScanJob(document_id=document.id, status="queued", attempts=0))
        imported.append(document.id)
    db.commit()
    return SuiteImportResult(imported=imported, unchanged=unchanged)
