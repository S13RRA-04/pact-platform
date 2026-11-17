from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _release_plan_item(client, login, mutate_headers, instructor: str, code: str) -> None:
    """Release a HARBORLINE plan item (e.g. an evidence batch) for the instructor's first cohort; idempotent."""
    login(instructor)
    cohort_id = client.get("/api/staff/cohorts").json()[0]["id"]
    plan = client.get(f"/api/cohorts/{cohort_id}/release-plan").json()
    item = next(i for i in plan["items"] if i["code"] == code)
    if item["state"] != "released":
        r = client.post(
            f"/api/cohorts/{cohort_id}/release-plan/{item['item_id']}/release",
            headers=mutate_headers,
            json={},
        )
        assert r.status_code == 200, r.text


def _assignment(client):
    response = client.get("/api/student/dashboard")
    assert response.status_code == 200
    return response.json()["assignments"][0]


def test_pathway_specific_workspaces(client, login):
    login("inv.brooks")
    investigator = _assignment(client)
    assert investigator["template_code"] == "E03-P02-INV"
    login("ana.ellis")
    analyst = _assignment(client)
    assert analyst["template_code"] == "E03-P02-ANA"
    assert client.get(f"/api/assignments/{investigator['id']}").status_code == 404


def test_non_m04_lessons_are_unapproved_authoring_shells(client, login):
    login("instr.lin")
    module = client.get("/api/curriculum/modules/M01")
    assert module.status_code == 200
    lesson = module.json()["lessons"][0]
    assert lesson["approval_status"] == "draft"
    assert "authoring shell" in lesson["title"].lower()
    assert "No authoritative lesson plan" in lesson["provenance_note"]


def test_instructor_controls_lesson_release_and_students_cannot_bypass_lock(client, login, mutate_headers):
    login("instr.lin")
    cohort_id = client.get("/api/staff/cohorts").json()[0]["id"]
    controls = client.get(f"/api/staff/cohorts/{cohort_id}/lesson-releases")
    assert controls.status_code == 200
    m01 = next(item for item in controls.json() if item["module_code"] == "M01")
    assert m01["released"] is False
    login("inv.brooks")
    assert client.get("/api/curriculum/modules/M01").json()["lessons"] == []
    login("instr.lin")
    released = client.post(
        f"/api/staff/cohorts/{cohort_id}/lesson-releases/{m01['lesson_id']}",
        json={"taught_at": None},
        headers=mutate_headers,
    )
    assert released.status_code == 200
    login("inv.brooks")
    assert client.get("/api/curriculum/modules/M01").json()["lessons"][0]["code"] == "M01-L1"
    login("admin.novak")
    assert any(c["id"] == cohort_id for c in client.get("/api/staff/cohorts").json())
    assert client.get(f"/api/staff/cohorts/{cohort_id}/lesson-releases").status_code == 200


def test_scheduled_and_bulk_lifecycle_controls(client, login, mutate_headers):
    login("instr.lin")
    cohort_id = client.get("/api/staff/cohorts").json()[0]["id"]
    controls = client.get(f"/api/staff/cohorts/{cohort_id}/lesson-releases").json()
    m02 = next(item for item in controls if item["module_code"] == "M02")
    future = datetime.now(UTC) + timedelta(days=1)
    scheduled = client.post(
        f"/api/staff/cohorts/{cohort_id}/lesson-releases/{m02['lesson_id']}",
        json={"lifecycle_state": "scheduled", "scheduled_for": future.isoformat()},
        headers=mutate_headers,
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["lifecycle_state"] == "scheduled"
    login("inv.brooks")
    assert client.get("/api/curriculum/modules/M02").json()["lessons"] == []
    login("instr.lin")
    bulk = client.post(
        f"/api/staff/cohorts/{cohort_id}/lesson-release-bulk",
        json={"module_code": "M02", "lifecycle_state": "released"},
        headers=mutate_headers,
    )
    assert bulk.status_code == 200
    assert next(x for x in bulk.json() if x["module_code"] == "M02")["released"] is True

    controls = client.get(f"/api/staff/cohorts/{cohort_id}/lesson-releases").json()
    m03 = next(item for item in controls if item["module_code"] == "M03")
    past = datetime.now(UTC) - timedelta(minutes=1)
    client.post(
        f"/api/staff/cohorts/{cohort_id}/lesson-releases/{m03['lesson_id']}",
        json={"lifecycle_state": "scheduled", "scheduled_for": past.isoformat()},
        headers=mutate_headers,
    )
    login("inv.brooks")
    assert client.get("/api/curriculum/modules/M03").json()["lessons"]
    notification = next(
        n for n in client.get("/api/student/notifications").json() if n["entity_id"] == str(m03["lesson_id"])
    )
    assert notification["read_at"] is None
    assert (
        client.post(
            f"/api/student/notifications/{notification['id']}/read", headers=mutate_headers
        ).status_code
        == 204
    )
    preferences = client.put(
        "/api/student/notification-preferences",
        headers=mutate_headers,
        json={
            "in_app_enabled": True,
            "content_release_enabled": False,
            "feedback_enabled": True,
            "digest_frequency": "daily",
        },
    )
    assert preferences.status_code == 200
    assert preferences.json()["content_release_enabled"] is False


def test_unreleased_and_cross_cohort_access_are_denied(client, login):
    login("inv.brooks")
    me = client.get("/api/me").json()
    cohort_id = me["memberships"][0]["cohort_id"]
    # H-ATR-01 exists in HARBORLINE but is only released with E08.
    assert client.get(f"/api/cohorts/{cohort_id}/evidence/H-ATR-01").status_code == 404
    assert client.get(f"/api/cohorts/{cohort_id + 1}/case").status_code in (403, 404)


def test_students_cannot_retrieve_staff_review(client, login):
    login("inv.brooks")
    assert client.get("/api/staff/submissions/999/review").status_code in (403, 404)


def test_draft_persists_and_submission_is_immutable(client, login, mutate_headers):
    _release_plan_item(client, login, mutate_headers, "instr.lin", "EVI-E03")
    login("inv.brooks")
    assignment = _assignment(client)
    aid = assignment["id"]
    payload = {
        "content": {
            "alternate_explanation": "H-PXY-01 counts bytes only; an approved backup is not excluded."
        },
        "cited_evidence": ["H-PXY-01"],
        "base_revision": 0,
    }
    saved = client.put(f"/api/assignments/{aid}/draft", json=payload, headers=mutate_headers)
    assert saved.status_code == 200
    assert client.get(f"/api/assignments/{aid}").json()["draft"]["content"] == payload["content"]
    submitted = client.post(f"/api/assignments/{aid}/submit", headers=mutate_headers)
    assert submitted.status_code == 200
    denied = client.put(
        f"/api/assignments/{aid}/draft",
        json={**payload, "base_revision": 1},
        headers=mutate_headers,
    )
    assert denied.status_code == 409
    artifact = client.get(f"/api/submissions/{submitted.json()['id']}").json()
    assert artifact["content_sha256"] == submitted.json()["content_sha256"]


def test_feedback_links_to_submission_without_mastery(client, login, mutate_headers):
    login("inv.brooks")
    assessments = client.get("/api/student/assessments").json()
    submission_id = assessments[0]["submission"]["id"]
    login("eval.shah")
    review = client.get(f"/api/staff/submissions/{submission_id}/review")
    assert review.status_code == 200
    criterion = review.json()["criteria"][0]
    recorded = client.post(
        f"/api/staff/submissions/{submission_id}/evaluations",
        headers=mutate_headers,
        json={
            "summary_comment": "Provisional feedback only.",
            "criterion_results": [{"criterion_id": criterion["id"], "observation": "observed"}],
            "objective_notes": [],
        },
    )
    assert recorded.status_code == 200
    queue = client.get(f"/api/staff/cohorts/{review.json()['submission']['cohort_id']}/grading-queue")
    assert queue.status_code == 200
    item = next(x for x in queue.json() if x["submission_id"] == submission_id)
    assert item["rubric_complete"] is False
    release = client.post(f"/api/staff/evaluations/{recorded.json()['id']}/release", headers=mutate_headers)
    assert release.status_code == 409
    login("inv.brooks")
    result = client.get("/api/student/assessments").json()[0]
    assert all(o["determination"] == "not_determined" for o in result["objectives"])


def test_complete_rubric_can_be_bulk_released(client, login, mutate_headers):
    login("inv.brooks")
    submission_id = client.get("/api/student/assessments").json()[0]["submission"]["id"]
    login("eval.shah")
    review = client.get(f"/api/staff/submissions/{submission_id}/review").json()
    recorded = client.post(
        f"/api/staff/submissions/{submission_id}/evaluations",
        headers=mutate_headers,
        json={
            "summary_comment": "All rubric criteria reviewed.",
            "criterion_results": [
                {"criterion_id": criterion["id"], "observation": "observed"}
                for criterion in review["criteria"]
            ],
            "objective_notes": [],
        },
    )
    assert recorded.status_code == 200
    released = client.post(
        "/api/staff/feedback/bulk-release",
        headers=mutate_headers,
        json={
            "evaluation_record_ids": [recorded.json()["id"]],
            "confirmation": "RELEASE FEEDBACK",
        },
    )
    assert released.status_code == 200
    assert released.json()["released_count"] == 1


def test_instructor_release_creates_audit_record(client, login, mutate_headers):
    login("instr.lin")
    cohort = client.get("/api/staff/cohorts").json()[0]
    preview = client.get(f"/api/cohorts/{cohort['id']}/staff/evidence-preview").json()
    approved = next(
        (i for i in preview["injects"] if i["approval_status"] == "approved" and not i["released"]), None
    )
    if approved is None:
        return
    response = client.post(
        f"/api/cohorts/{cohort['id']}/staff/injects/{approved['id']}/release",
        headers=mutate_headers,
        json={"note": "Automated release verification"},
    )
    assert response.status_code == 200
    login("secops.kim")
    events = client.get("/api/admin/audit-events")
    assert events.status_code == 200
    assert any(e["action"] == "inject.release" for e in events.json())
