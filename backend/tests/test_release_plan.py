"""Scenario release plans (Case HARBORLINE): package approval, activation, triggers and per-cohort control."""

from __future__ import annotations

import itertools
import time

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db import get_engine

H = {"X-PACT-Request": "1"}
_seq = itertools.count(1)


def _as(client: TestClient, username: str) -> TestClient:
    c = TestClient(client.app)
    assert c.post("/api/dev/login", json={"username": username}, headers=H).status_code == 200
    return c


def _sql(statement: str, **params):
    with get_engine(Settings().test_database_url).begin() as conn:
        return conn.execute(text(statement), params)


def _base_version(editor: TestClient) -> dict:
    return next(
        v
        for v in editor.get("/api/admin/scenario-versions").json()
        if v["case_code"] == "HARBORLINE" and v["version_label"] == "0.3"
    )


def _cohort_ids(client: TestClient) -> dict[str, int]:
    return {c["code"]: c["id"] for c in _as(client, "admin.novak").get("/api/admin/cohorts").json()}


def _new_cohort(client: TestClient, start: str = "2026-01-05", end: str = "2026-01-09") -> int:
    admin = _as(client, "admin.novak")
    code = f"PLAN-{next(_seq):02d}{int(time.time()) % 10000}"
    r = admin.post(
        "/api/admin/cohorts",
        headers=H,
        json={"code": code, "name": f"Plan test {code}", "start_date": start, "end_date": end},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _clone(client: TestClient, prefix: str) -> dict:
    editor = _as(client, "curr.ortega")
    base = _base_version(editor)
    label = f"{prefix}.{next(_seq)}-t{int(time.time()) % 1000}"
    r = editor.post(
        f"/api/admin/scenario-versions/{base['id']}/clone", headers=H, json={"version_label": label}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _submit_and_approve(client: TestClient, sv: dict) -> None:
    editor, approver = _as(client, "curr.ortega"), _as(client, "appr.whitfield")
    assert editor.post(f"/api/admin/scenario-versions/{sv['id']}/submit", headers=H).status_code == 200
    pending = next(
        a
        for a in approver.get("/api/admin/approvals").json()
        if a["entity_type"] == "scenario_version"
        and a["status"] == "pending"
        and a["entity_code"].endswith(sv["version_label"])
    )
    r = approver.post(
        f"/api/admin/approvals/{pending['id']}/decision", headers=H, json={"decision": "approved"}
    )
    assert r.status_code == 200, r.text


def _item(plan: dict, code: str) -> dict:
    return next(i for i in plan["items"] if i["code"] == code)


def _act(c: TestClient, cohort_id: int, plan: dict, code: str, action: str, reason: str | None = None):
    return c.post(
        f"/api/cohorts/{cohort_id}/release-plan/{_item(plan, code)['item_id']}/{action}",
        headers=H,
        json={"reason": reason} if reason else {},
    )


# --- the seeded HARBORLINE plan --------------------------------------------------------------------------
def test_harborline_plan_is_built_from_the_v03_suite(client):
    editor = _as(client, "curr.ortega")
    base = _base_version(editor)
    assert base["approval_status"] == "approved" and base["locked"]
    detail = editor.get(f"/api/admin/scenario-versions/{base['id']}").json()
    codes = {i["code"]: i for i in detail["items"]}
    # One packet, one evidence batch (two for E06) and one instructor key per exercise; K01/K02; v0.5 blocks.
    for ex in ("E00", "E01", "E02", "EPROV", "E03", "E04", "E05", "E07", "E08", "P05"):
        assert codes[f"PKT-{ex}"]["item_type"] == "document"
        assert codes[f"AK-{ex}"]["audience"] == "staff"
    assert {"EVI-E06A", "EVI-E06B", "CH-K01", "CH-K02", "AK-K01", "DOC-TUE-EARLY"} <= set(codes)
    assert (
        codes["PKT-E03"]["trigger_module_code"] == "M04"
        and codes["PKT-E03"]["trigger_lesson_state"] == "taught"
    )
    # Student-facing knowledge-check text never carries the key; the staff key does.
    assert "INSTRUCTOR KEY" not in codes["CH-K01"]["body"] and "INSTRUCTOR KEY" in codes["AK-K01"]["body"]
    assert (
        "Release checklist" in codes["AK-E03"]["body"]
        and "Annotated instructor key" in codes["AK-E03"]["body"]
    )
    assert codes["CH-K02"]["scored"] and codes["CH-K02"]["instrument_code"] == "K02"


def test_approved_plan_is_locked_and_changes_go_into_a_clone(client):
    editor = _as(client, "curr.ortega")
    base = _base_version(editor)
    challenge = {
        "code": "CH-NEW",
        "item_type": "challenge",
        "title": "New",
        "body": "Do the thing",
        "trigger_type": "manual",
    }
    assert (
        editor.post(f"/api/admin/scenario-versions/{base['id']}/items", headers=H, json=challenge).status_code
        == 409
    )

    draft = _clone(client, "1")
    assert draft["approval_status"] == "draft" and not draft["locked"]
    assert draft["item_count"] == base["item_count"]
    assert (
        editor.post(
            f"/api/admin/scenario-versions/{draft['id']}/items", headers=H, json=challenge
        ).status_code
        == 201
    )
    bad = [
        {**challenge, "code": "CH-X1", "audience": "staff"},
        {**challenge, "code": "CH-X2", "trigger_type": "after_item", "trigger_after_code": "NOPE"},
        {**challenge, "code": "CH-X3", "scored": True},
        {
            **challenge,
            "code": "CH-X4",
            "trigger_type": "scheduled",
            "trigger_day": "Tue",
            "trigger_time": "25:00",
        },
        {"code": "DOC-X5", "item_type": "document", "title": "No code", "trigger_type": "manual"},
    ]
    for body in bad:
        assert (
            editor.post(f"/api/admin/scenario-versions/{draft['id']}/items", headers=H, json=body).status_code
            == 422
        ), body["code"]

    assert editor.post(f"/api/admin/scenario-versions/{draft['id']}/submit", headers=H).status_code == 200
    assert (
        editor.post(
            f"/api/admin/scenario-versions/{draft['id']}/items",
            headers=H,
            json={**challenge, "code": "CH-LATE"},
        ).status_code
        == 409
    )
    mine = next(
        a
        for a in editor.get("/api/admin/approvals").json()
        if a["entity_type"] == "scenario_version"
        and a["status"] == "pending"
        and a["entity_code"].endswith(draft["version_label"])
    )
    assert (
        editor.post(
            f"/api/admin/approvals/{mine['id']}/decision", headers=H, json={"decision": "approved"}
        ).status_code
        == 403
    )
    _sql(
        "UPDATE release_items SET title = 'tampered' WHERE scenario_version_id = :v AND code = 'CH-NEW'",
        v=draft["id"],
    )
    approver = _as(client, "appr.whitfield")
    assert (
        approver.post(
            f"/api/admin/approvals/{mine['id']}/decision", headers=H, json={"decision": "approved"}
        ).status_code
        == 409
    )
    _sql(
        "UPDATE release_items SET title = 'New' WHERE scenario_version_id = :v AND code = 'CH-NEW'",
        v=draft["id"],
    )
    assert (
        approver.post(
            f"/api/admin/approvals/{mine['id']}/decision", headers=H, json={"decision": "approved"}
        ).status_code
        == 200
    )


def test_glass_harbor_is_retired_and_activation_rules_hold(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    versions = editor.get("/api/admin/scenario-versions").json()
    assert all(v["case_code"] != "GLASS-HARBOR" or v["approval_status"] == "retired" for v in versions)
    base = _base_version(editor)
    draft = _clone(client, "2")
    cohort_id = _new_cohort(client)
    url = f"/api/admin/cohorts/{cohort_id}/activate-scenario"
    assert admin.post(url, headers=H, json={"scenario_version_id": draft["id"]}).status_code == 409
    assert editor.post(url, headers=H, json={"scenario_version_id": base["id"]}).status_code == 403
    plan = admin.post(url, headers=H, json={"scenario_version_id": base["id"]})
    assert plan.status_code == 200, plan.text
    assert plan.json()["case_code"] == "HARBORLINE" and len(plan.json()["items"]) == base["item_count"]
    assert admin.post(url, headers=H, json={"scenario_version_id": base["id"]}).status_code == 200
    # E03 assignments timed from the POI block in cohort-local time (Tue 10:30 America/Chicago = 16:30Z in January).
    opens = _sql("SELECT min(opens_at) FROM assignments WHERE cohort_id = :c", c=cohort_id).scalar()
    assert opens is not None and opens.isoformat().startswith("2026-01-06T16:30")


# --- release control --------------------------------------------------------------------------------------
def test_release_notifies_and_withdraw_hides_evidence(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor, student = _as(client, "instr.reyes"), _as(client, "inv.harper")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    assert _item(plan, "EVI-E03")["state"] == "pending"
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 404

    released = _act(instructor, cid, plan, "EVI-E03", "release")
    assert released.status_code == 200, released.text
    evidence = student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01")
    assert evidence.status_code == 200
    body = evidence.json()
    assert (
        body["observed_as_recorded"].startswith("2026-10-25T04:09:03Z")
        and "network_events.csv" in body["content"]
    )
    assert "Collector, export method and custody chain are not stated" in body["provenance"]
    assert any(n["title"] == "New case evidence" for n in student.get("/api/student/notifications").json())

    assert _act(instructor, cid, plan, "EVI-E03", "withdraw").status_code == 422  # reason required
    withdrawn = _act(instructor, cid, plan, "EVI-E03", "withdraw", "Released early by mistake")
    assert withdrawn.status_code == 200 and _item(withdrawn.json(), "EVI-E03")["state"] == "withdrawn"
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 404
    assert _act(instructor, cid, plan, "EVI-E03", "release").status_code == 200
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 200


def test_undated_records_stay_out_of_the_timeline(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor, student = _as(client, "instr.reyes"), _as(client, "inv.harper")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    if _item(plan, "EVI-E02")["state"] != "released":
        assert _act(instructor, cid, plan, "EVI-E02", "release").status_code == 200
    vendor = student.get(f"/api/cohorts/{cid}/evidence/H-VND-01").json()
    assert vendor["observed_at"] is None and vendor["observed_as_recorded"] == "Not recorded in source"
    timeline = student.get(f"/api/cohorts/{cid}/case").json()["timeline"]
    assert all(t["evidence_code"] != "H-VND-01" for t in timeline)


def test_answer_keys_and_unauthorized_scoring_stay_blocked(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    for code, expected in (("AK-E03", "staff only"), ("CH-K01", "not authorized")):
        r = _act(instructor, cid, plan, code, "release")
        assert r.status_code == 409 and expected in r.json()["detail"], (code, r.text)


def test_hold_and_resume(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    held = _act(instructor, cid, plan, "DOC-FRI", "hold", "Panel room not ready")
    assert held.status_code == 200 and _item(held.json(), "DOC-FRI")["state"] == "held"
    assert _act(instructor, cid, plan, "DOC-FRI", "hold").status_code == 409
    resumed = _act(instructor, cid, plan, "DOC-FRI", "resume")
    assert resumed.status_code == 200 and _item(resumed.json(), "DOC-FRI")["state"] == "pending"


def test_triggers_cascades_and_cloned_injects_need_their_own_approval(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    draft = _clone(client, "3")
    url = f"/api/admin/scenario-versions/{draft['id']}/items"
    for body in (
        {
            "code": "CH-MON-WARMUP",
            "item_type": "challenge",
            "title": "Monday warm-up",
            "body": "Warm up",
            "trigger_type": "scheduled",
            "trigger_day": "Mon",
            "trigger_time": "09:00",
            "audience": "investigator",
        },
        {
            "code": "CH-FRI-LATER",
            "item_type": "challenge",
            "title": "Later",
            "body": "Later",
            "trigger_type": "scheduled",
            "trigger_day": "Fri",
            "trigger_time": "11:00",
        },
        {
            "code": "CH-AFTER-PKT",
            "item_type": "challenge",
            "title": "After the packet",
            "body": "Follow-on",
            "trigger_type": "after_item",
            "trigger_after_code": "PKT-E03",
        },
    ):
        assert editor.post(url, headers=H, json=body).status_code == 201, body["code"]
    _submit_and_approve(client, draft)

    past = _new_cohort(client, "2026-02-02", "2026-02-06")
    plan = admin.post(
        f"/api/admin/cohorts/{past}/activate-scenario", headers=H, json={"scenario_version_id": draft["id"]}
    ).json()
    assert _item(plan, "CH-MON-WARMUP")["state"] == "released"
    assert _item(plan, "CH-MON-WARMUP")["due_at"].startswith("2026-02-02T15:00")  # 09:00 America/Chicago
    future = _new_cohort(client, "2030-03-04", "2030-03-08")
    plan2 = admin.post(
        f"/api/admin/cohorts/{future}/activate-scenario", headers=H, json={"scenario_version_id": draft["id"]}
    ).json()
    assert _item(plan2, "CH-MON-WARMUP")["state"] == "pending"

    # Cloned injects are drafts: the plan is approved but the evidence content is not.
    r = _act(admin, past, plan, "EVI-E03", "release")
    assert r.status_code == 409 and "not been approved" in r.json()["detail"]

    # Lesson stage → packet document; packet → dependent challenge opens automatically.
    lessons = admin.get(f"/api/staff/cohorts/{past}/lesson-releases").json()
    m04 = next(lesson for lesson in lessons if lesson["module_code"] == "M04")
    assert (
        admin.post(
            f"/api/staff/cohorts/{past}/lesson-releases/{m04['lesson_id']}",
            headers=H,
            json={"lifecycle_state": "released"},
        ).status_code
        == 200
    )
    plan = admin.get(f"/api/cohorts/{past}/release-plan").json()
    assert _item(plan, "DOC-TUE-EARLY")["state"] == "released"
    assert _item(plan, "PKT-E03")["state"] == "pending"  # gated on "taught"
    assert (
        admin.post(
            f"/api/staff/cohorts/{past}/lesson-releases/{m04['lesson_id']}",
            headers=H,
            json={"lifecycle_state": "taught"},
        ).status_code
        == 200
    )
    plan = admin.get(f"/api/cohorts/{past}/release-plan").json()
    assert _item(plan, "PKT-E03")["state"] == "released"
    assert _item(plan, "CH-AFTER-PKT")["state"] == "released"

    # The student sees the released packet (Course Materials) and pathway-targeted challenges only.
    enrolled = admin.post(
        f"/api/admin/cohorts/{past}/members",
        headers=H,
        json={
            "user_id": _sql("SELECT id FROM users WHERE username='inv.harper'").scalar(),
            "role": "student",
            "pathway": "investigator",
        },
    )
    assert enrolled.status_code == 200
    student = _as(client, "inv.harper")
    codes = {m["document_code"] for m in student.get("/api/student/materials").json()}
    assert "PKT-E03" in codes
    challenges = {c["code"] for c in student.get("/api/student/challenges").json()}
    assert {"CH-MON-WARMUP", "CH-AFTER-PKT"} <= challenges
    membership = next(m for m in enrolled.json()["members"] if m["username"] == "inv.harper")
    admin.patch(
        f"/api/admin/cohorts/{past}/members/{membership['membership_id']}",
        headers=H,
        json={"status": "withdrawn"},
    )


def test_plan_access_is_role_and_cohort_scoped(client):
    cohorts = _cohort_ids(client)
    demo1, demo2 = cohorts["PACT-DEMO-01"], cohorts["PACT-DEMO-02"]
    assert _as(client, "inv.brooks").get(f"/api/cohorts/{demo1}/release-plan").status_code in (403, 404)
    evaluator = _as(client, "eval.shah")
    view = evaluator.get(f"/api/cohorts/{demo1}/release-plan")
    assert view.status_code == 200 and view.json()["can_control"] is False
    ak = _item(view.json(), "AK-E03")
    assert "Release checklist" in ak["preview"]  # staff can read instructor keys
    assert (
        evaluator.post(
            f"/api/cohorts/{demo1}/release-plan/{ak['item_id']}/hold", headers=H, json={}
        ).status_code
        == 403
    )
    assert _as(client, "instr.lin").get(f"/api/cohorts/{demo2}/release-plan").status_code == 404
    assert _as(client, "inv.brooks").get("/api/admin/scenario-versions").status_code == 403
    assert _as(client, "instr.lin").get("/api/student/challenges").status_code == 403
