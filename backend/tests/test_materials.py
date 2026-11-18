"""Course materials: released packets reach students; nothing else does; staff get instructor materials."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db import get_engine

H = {"X-PACT-Request": "1"}


def _as(client: TestClient, username: str) -> TestClient:
    c = TestClient(client.app)
    assert c.post("/api/dev/login", json={"username": username}, headers=H).status_code == 200
    return c


def _doc_id(code: str) -> int:
    with get_engine(Settings().test_database_url).connect() as conn:
        return conn.scalar(
            text("SELECT max(id) FROM curriculum_documents WHERE document_code = :c"), {"c": code}
        )


def test_suite_documents_imported_scanned_approved_with_correct_audience(client):
    with get_engine(Settings().test_database_url).connect() as conn:
        rows = {
            r.document_code: r
            for r in conn.execute(
                text(
                    "SELECT DISTINCT ON (document_code) document_code, audience, approval_status, scan_status "
                    "FROM curriculum_documents WHERE document_code LIKE 'PKT-%' OR document_code LIKE 'HBL%' "
                    "ORDER BY document_code, version_number DESC"
                )
            )
        }
    # v0.5 staged packets (student) and instructor master files (instructor only).
    assert {f"HBL-{n:02d}" for n in range(1, 18)} <= set(rows)
    assert all(rows[f"HBL-{n:02d}"].audience == "student" for n in range(1, 18))
    for code in ("HBL-INSTR", "HBL-RELREG", "HBL-SRCREG", "HBL-README"):
        assert rows[code].audience == "instructor", code  # "NEVER distribute this folder to students"
    # v0.3 suite stays as staff reference material.
    for code in ("HBL3-MASTER", "HBL3-KEY", "HBL3-KC", "HBL3-DOSSIER", "HBL3-REGISTER", "HBL3-FACULTY"):
        assert rows[code].audience == "instructor", code
    assert rows["PKT-E03"].audience == "student"
    assert all(r.scan_status == "clean" and r.approval_status == "approved" for r in rows.values())


def test_student_downloads_only_packets_released_to_their_squad(client):
    admin = _as(client, "admin.novak")
    cohort_id = next(c["id"] for c in admin.get("/api/admin/cohorts").json() if c["code"] == "PACT-DEMO-01")
    student = _as(client, "ana.ellis")  # squad Alpha: case A

    # Unreleased packet: no listing, no link. v0.3 packets are never released under v0.5.
    assert all(m["document_code"] != "HBL-01" for m in student.get("/api/student/materials").json())
    assert student.post(f"/api/materials/{_doc_id('HBL-01')}/download-link", headers=H).status_code == 404
    assert student.post(f"/api/materials/{_doc_id('PKT-E00')}/download-link", headers=H).status_code == 404
    # Instructor-only material is never available to students.
    for code in ("HBL-INSTR", "HBL3-KEY"):
        assert student.post(f"/api/materials/{_doc_id(code)}/download-link", headers=H).status_code == 404

    def release(code: str) -> dict:
        plan = admin.get(f"/api/cohorts/{cohort_id}/release-plan").json()
        item = next(i for i in plan["items"] if i["code"] == code)
        if item["state"] != "released":
            r = admin.post(
                f"/api/cohorts/{cohort_id}/release-plan/{item['item_id']}/release", headers=H, json={}
            )
            assert r.status_code == 200, r.text
        return item

    item = release("PKT-01")
    release("PKT-03")  # case C: no squad in this cohort holds it
    listed = {m["document_code"]: m for m in student.get("/api/student/materials").json()}
    assert "HBL-01" in listed and listed["HBL-01"]["cohort_code"] == "PACT-DEMO-01"
    assert "HBL-03" not in listed
    assert student.post(f"/api/materials/{_doc_id('HBL-03')}/download-link", headers=H).status_code == 404
    link = student.post(f"/api/materials/{listed['HBL-01']['id']}/download-link", headers=H)
    assert link.status_code == 200
    url = link.json()["url"]
    got = student.get(url)
    assert got.status_code == 200 and got.content[:2] == b"PK"  # a .docx (zip) file
    assert "attachment;" in got.headers["content-disposition"]

    # Links are bound to the user and re-checked at use: another student, or a withdrawn release, is refused.
    assert _as(client, "inv.brooks").get(url).status_code == 403
    assert (
        admin.post(
            f"/api/cohorts/{cohort_id}/release-plan/{item['item_id']}/withdraw",
            headers=H,
            json={"reason": "test withdrawal"},
        ).status_code
        == 200
    )
    assert student.get(url).status_code == 404
    assert all(m["document_code"] != "HBL-01" for m in student.get("/api/student/materials").json())
    admin.post(f"/api/cohorts/{cohort_id}/release-plan/{item['item_id']}/release", headers=H, json={})


def test_staff_get_instructor_materials_and_decks(client):
    instructor = _as(client, "instr.lin")
    codes = {m["document_code"] for m in instructor.get("/api/staff/materials").json()}
    assert {"HBL-INSTR", "HBL-RELREG", "HBL-01", "HBL3-MASTER", "HBL3-KEY", "PKT-E03"} <= codes
    link = instructor.post(f"/api/materials/{_doc_id('HBL-INSTR')}/download-link", headers=H)
    assert link.status_code == 200 and instructor.get(link.json()["url"]).status_code == 200
    assert _as(client, "inv.brooks").get("/api/staff/materials").status_code == 403

    deck = instructor.get("/api/curriculum/modules/M04/presentation").json()
    assert deck is not None and deck["document_code"] == "M04" and deck["slides"]
    # Decks are still drafts: students do not see them yet.
    assert _as(client, "inv.brooks").get("/api/curriculum/modules/M04/presentation").json() is None


def test_imports_are_idempotent_after_scanning(client):
    """Scanning rewrites Office files (new hash); a re-import must still recognise the original upload."""
    from sqlalchemy.orm import Session

    from app.curriculum_import.archives import import_curriculum_archives
    from app.curriculum_import.exercise_suite import import_exercise_suite
    from app.seed.harborline import INSTRUCTOR_ZIP, STUDENT_ZIP, SUITE_DIR

    with Session(get_engine(Settings().test_database_url)) as db:
        again = import_exercise_suite(db, SUITE_DIR)
        archives = import_curriculum_archives(db, [STUDENT_ZIP, INSTRUCTOR_ZIP])
    assert again.imported == [] and again.unchanged >= 20
    assert archives.imported == 0 and archives.deduplicated >= 21
