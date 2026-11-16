from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_engine
from app.models import ApprovalRequest, CurriculumDocument
from app.services.background_jobs import process_scan_job


def test_replacement_stays_quarantined_until_worker_scans(client, login, mutate_headers):
    login("curr.ortega")
    documents = client.get("/api/staff/curriculum-documents").json()
    current = next(item for item in documents if item["document_code"] == "M04")
    source = Path(
        "../pact curriculum/PACT_Redesigned_Presentation_Suite_v0.2/Presentations/04_Digital_Evidence_and_Acquisition_Strategy.pptx"
    )
    replacement_bytes = source.read_bytes() + b"\nreplacement-version-test"
    queued = client.post(
        f"/api/admin/curriculum-documents/{current['id']}/replacement",
        headers=mutate_headers,
        files={
            "file": (
                source.name,
                replacement_bytes,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        },
    )
    assert queued.status_code == 200
    assert queued.json()["scan_status"] == "queued"
    settings = Settings()
    with Session(get_engine(settings.test_database_url)) as db:
        assert process_scan_job(db, settings) == 1
        document = db.get(CurriculumDocument, queued.json()["document_id"])
        assert document.scan_status == "clean"
        assert (
            db.query(ApprovalRequest)
            .filter_by(entity_type="curriculum_document", entity_id=document.id)
            .one()
        )
