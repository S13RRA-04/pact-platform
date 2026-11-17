"""Regression tests for review findings: quarantine bypass, schema drift, DB-level immutability, stuck jobs."""

import io
import zipfile
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command as alembic_command
from app.config import Settings
from app.db import get_engine
from app.models import CurriculumDocument, DocumentScanJob
from app.services.background_jobs import process_scan_job

BACKEND_DIR = Path(__file__).resolve().parents[1]
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SOURCE = Path(
    "../pact curriculum/PACT_Redesigned_Presentation_Suite_v0.2/Presentations/"
    "04_Digital_Evidence_and_Acquisition_Strategy.pptx"
)


def _engine():
    return get_engine(Settings().test_database_url)


def _drain_queue(settings: Settings) -> None:
    with Session(_engine()) as db:
        while process_scan_job(db, settings):
            pass


def _variant(marker: str) -> bytes:
    """A PPTX whose *sanitized* content differs (bytes appended after the zip are stripped by disarm)."""
    buffer = io.BytesIO(SOURCE.read_bytes())
    with zipfile.ZipFile(buffer, "a") as package:
        package.writestr(f"docProps/pact-test-{marker}.xml", f"<test>{marker}</test>")
    return buffer.getvalue()


def test_duplicate_after_disarm_is_rejected_plainly(client, login, mutate_headers):
    settings = Settings()
    _drain_queue(settings)
    login("curr.ortega")
    current = next(
        d for d in client.get("/api/staff/curriculum-documents").json() if d["document_code"] == "M04"
    )
    # Differs from the source only after the end of the zip, so it disarms to existing content.
    upload = client.post(
        f"/api/admin/curriculum-documents/{current['id']}/replacement",
        headers=mutate_headers,
        files={"file": ("dup.pptx", SOURCE.read_bytes() + b"\ntrailing-bytes-only", PPTX)},
    )
    assert upload.status_code == 200, upload.text
    with Session(_engine()) as db:
        assert process_scan_job(db, settings) == 1
        job = db.scalar(
            select(DocumentScanJob).where(DocumentScanJob.document_id == upload.json()["document_id"])
        )
        assert job.status == "failed"
        assert "identical to" in job.error


def test_quarantined_document_cannot_be_downloaded(client, login, mutate_headers):
    settings = Settings()
    _drain_queue(settings)
    login("curr.ortega")
    current = next(
        d for d in client.get("/api/staff/curriculum-documents").json() if d["document_code"] == "M04"
    )
    upload = client.post(
        f"/api/admin/curriculum-documents/{current['id']}/replacement",
        headers=mutate_headers,
        files={"file": ('evil"name.pptx', _variant("download"), PPTX)},
    )
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["document_id"]

    link = client.post(f"/api/admin/curriculum-documents/{doc_id}/download-link", headers=mutate_headers)
    assert link.status_code == 200
    blocked = client.get(link.json()["url"])
    assert blocked.status_code == 409  # still quarantined: bytes must not leave storage

    with Session(_engine()) as db:
        assert process_scan_job(db, settings) == 1
        assert db.get(CurriculumDocument, doc_id).scan_status == "clean"
    allowed = client.get(
        client.post(f"/api/admin/curriculum-documents/{doc_id}/download-link", headers=mutate_headers).json()[
            "url"
        ]
    )
    assert allowed.status_code == 200
    disposition = allowed.headers["content-disposition"]
    # The plain filename parameter contains only safe characters; the original goes in RFC 5987 form.
    plain = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert plain.endswith(".pptx") and all(c.isalnum() or c in "._- " for c in plain)
    assert "filename*=UTF-8''" in disposition


def test_download_link_stops_working_when_role_is_revoked(client, login, mutate_headers):
    login("curr.ortega")
    current = next(
        d
        for d in client.get("/api/staff/curriculum-documents").json()
        if d["document_code"] == "M04" and d.get("scan_status", "clean") == "clean"
    )
    url = client.post(
        f"/api/admin/curriculum-documents/{current['id']}/download-link", headers=mutate_headers
    ).json()["url"]
    with _engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM user_roles WHERE role = 'curriculum_editor' AND user_id = "
                "(SELECT id FROM users WHERE username = 'curr.ortega')"
            )
        )
    try:
        assert client.get(url).status_code == 403
    finally:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_roles (user_id, role, created_at) "
                    "SELECT id, 'curriculum_editor', now() FROM users WHERE username = 'curr.ortega'"
                )
            )


def test_scan_job_without_uploader_fails_terminally(client):
    settings = Settings()
    _drain_queue(settings)
    with Session(_engine()) as db:
        template = db.scalar(select(CurriculumDocument).order_by(CurriculumDocument.id).limit(1))
        orphan = CurriculumDocument(
            course_version_id=template.course_version_id,
            module_id=template.module_id,
            version_number=99,
            document_code=template.document_code,
            title="orphan provenance test",
            media_type=template.media_type,
            source_filename="orphan.pptx",
            source_locator="test",
            object_key="quarantine/test/orphan.pptx",
            source_sha256="0" * 64,
            byte_size=1,
            approval_status="draft",
            scan_status="queued",
            scan_details={},
            provenance={},
        )
        db.add(orphan)
        db.flush()
        db.add(DocumentScanJob(document_id=orphan.id))
        db.commit()
        doc_id = orphan.id

        assert process_scan_job(db, settings) == 1
        db.expire_all()
        job = db.scalar(select(DocumentScanJob).where(DocumentScanJob.document_id == doc_id))
        assert job.status == "failed"
        assert "uploader" in (job.error or "")
        assert db.get(CurriculumDocument, doc_id).scan_status == "rejected"
        # Terminal: the job is not retried forever.
        assert process_scan_job(db, settings) == 0


def test_append_only_tables_reject_update_and_delete_at_database_level(client, login):
    login("inv.brooks")  # guarantees at least one audit row exists
    with _engine().connect() as conn:
        triggers = set(
            conn.scalars(text("SELECT tgname FROM pg_trigger WHERE tgname LIKE '%\\_append\\_only'"))
        )
    assert triggers == {
        f"{t}_append_only"
        for t in (
            "submissions",
            "evaluation_records",
            "criterion_results",
            "objective_evidence_notes",
            "feedback_releases",
            "audit_events",
        )
    }
    for statement in (
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
    ):
        with _engine().connect() as conn, pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text(statement))


def test_models_match_migrations(client):
    config = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["url"] = Settings().test_database_url
    alembic_command.check(config)  # raises AutogenerateDiffsDetected on drift
