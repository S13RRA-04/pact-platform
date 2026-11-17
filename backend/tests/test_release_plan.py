"""Scenario release plans: package approval, activation, triggers, and per-cohort control."""

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
        if v["case_code"] == "GLASS-HARBOR" and v["version_label"] == "1.0-dev"
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


def _approve_latest(client: TestClient, sv_id: int) -> None:
    approver = _as(client, "appr.whitfield")
    pending = next(
        a
        for a in approver.get("/api/admin/approvals").json()
        if a["entity_type"] == "scenario_version"
        and a["status"] == "pending"
        and a["entity_code"].endswith(_version_label(client, sv_id))
    )
    r = approver.post(
        f"/api/admin/approvals/{pending['id']}/decision",
        headers=H,
        json={"decision": "approved", "note": "test"},
    )
    assert r.status_code == 200, r.text


def _version_label(client: TestClient, sv_id: int) -> str:
    return _as(client, "curr.ortega").get(f"/api/admin/scenario-versions/{sv_id}").json()["version_label"]


def _item(plan: dict, code: str) -> dict:
    return next(i for i in plan["items"] if i["code"] == code)


# --- authoring and approval --------------------------------------------------------------------------
def test_approved_plan_is_locked_and_changes_go_into_a_clone(client):
    editor = _as(client, "curr.ortega")
    base = _base_version(editor)
    assert base["approval_status"] == "approved" and base["locked"]
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

    label = f"1.{next(_seq)}-t{int(time.time()) % 1000}"
    clone = editor.post(
        f"/api/admin/scenario-versions/{base['id']}/clone", headers=H, json={"version_label": label}
    )
    assert clone.status_code == 201, clone.text
    draft = clone.json()
    assert draft["approval_status"] == "draft" and not draft["locked"]
    assert draft["item_count"] == base["item_count"]
    added = editor.post(f"/api/admin/scenario-versions/{draft['id']}/items", headers=H, json=challenge)
    assert added.status_code == 201, added.text

    # Validation: staff audience only for answer keys; after_item must exist; no cycles; scored needs instrument.
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
    ]
    for body in bad:
        assert (
            editor.post(f"/api/admin/scenario-versions/{draft['id']}/items", headers=H, json=body).status_code
            == 422
        ), body["code"]

    submitted = editor.post(f"/api/admin/scenario-versions/{draft['id']}/submit", headers=H)
    assert submitted.status_code == 200 and submitted.json()["approval_status"] == "pending"
    assert (
        editor.post(
            f"/api/admin/scenario-versions/{draft['id']}/items",
            headers=H,
            json={**challenge, "code": "CH-LATE"},
        ).status_code
        == 409
    )  # frozen while pending

    approvals = editor.get("/api/admin/approvals").json()
    mine = next(
        a
        for a in approvals
        if a["entity_type"] == "scenario_version"
        and a["status"] == "pending"
        and a["entity_code"].endswith(label)
    )
    assert (
        editor.post(
            f"/api/admin/approvals/{mine['id']}/decision", headers=H, json={"decision": "approved"}
        ).status_code
        == 403
    )  # editor is not the approver

    # Tampering after submission is caught by the pinned hash.
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
    final = editor.get(f"/api/admin/scenario-versions/{draft['id']}").json()
    assert final["approval_status"] == "approved" and final["locked"]


def test_activation_requires_an_approved_version_and_one_version_per_cohort(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    base = _base_version(editor)
    draft = editor.post(
        f"/api/admin/scenario-versions/{base['id']}/clone",
        headers=H,
        json={"version_label": f"2.{next(_seq)}-t{int(time.time()) % 1000}"},
    ).json()
    cohort_id = _new_cohort(client)
    url = f"/api/admin/cohorts/{cohort_id}/activate-scenario"
    assert admin.post(url, headers=H, json={"scenario_version_id": draft["id"]}).status_code == 409
    assert editor.post(url, headers=H, json={"scenario_version_id": base["id"]}).status_code == 403
    plan = admin.post(url, headers=H, json={"scenario_version_id": base["id"]})
    assert plan.status_code == 200, plan.text
    assert plan.json()["case_code"] == "GLASS-HARBOR" and len(plan.json()["items"]) == base["item_count"]
    assert (
        admin.post(url, headers=H, json={"scenario_version_id": base["id"]}).status_code == 200
    )  # idempotent
    other = _sql(
        "SELECT id FROM scenario_versions WHERE locked AND approval_status = 'approved' AND id <> :b LIMIT 1",
        b=base["id"],
    ).scalar()
    if other:
        assert admin.post(url, headers=H, json={"scenario_version_id": other}).status_code == 409
    # Activation created the E03 assignments, timed from the POI block in cohort-local time (Tue 10:30 CST).
    due = _sql("SELECT min(opens_at) FROM assignments WHERE cohort_id = :c", c=cohort_id).scalar()
    assert due is not None and due.isoformat().startswith("2026-01-06T16:30")


# --- release control -----------------------------------------------------------------------------------
def test_release_cascades_notifies_and_withdraw_hides_evidence(client):
    cohorts = _cohort_ids(client)
    cid = cohorts["PACT-DEMO-02"]
    instructor, student = _as(client, "instr.reyes"), _as(client, "inv.harper")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    inj, challenge = _item(plan, "EVI-INJ-01"), _item(plan, "CH-E03-TRIAGE")
    assert inj["state"] == "pending" and challenge["state"] == "pending"
    assert student.get(f"/api/cohorts/{cid}/evidence/EV-006").status_code == 404
    assert all(c["code"] != "CH-E03-TRIAGE" for c in student.get("/api/student/challenges").json())

    # Prerequisite rule: the challenge cannot jump ahead of its inject.
    early = instructor.post(
        f"/api/cohorts/{cid}/release-plan/{challenge['item_id']}/release", headers=H, json={}
    )
    assert early.status_code == 409 and "Waiting for EVI-INJ-01" in early.json()["detail"]

    released = instructor.post(
        f"/api/cohorts/{cid}/release-plan/{inj['item_id']}/release", headers=H, json={}
    )
    assert released.status_code == 200, released.text
    assert _item(released.json(), "CH-E03-TRIAGE")["state"] == "released"  # opened automatically
    assert student.get(f"/api/cohorts/{cid}/evidence/EV-006").status_code == 200
    challenges = student.get("/api/student/challenges").json()
    assert any(c["code"] == "CH-E03-TRIAGE" and c["time_limit_minutes"] == 15 for c in challenges)
    assert all(c["code"] != "AK-CH-E03-TRIAGE" for c in challenges)  # answer key never reaches students
    notes = student.get("/api/student/notifications").json()
    assert any(n["title"] == "New case evidence" for n in notes) and any(
        n["title"] == "New challenge" for n in notes
    )

    no_reason = instructor.post(
        f"/api/cohorts/{cid}/release-plan/{inj['item_id']}/withdraw", headers=H, json={}
    )
    assert no_reason.status_code == 422
    withdrawn = instructor.post(
        f"/api/cohorts/{cid}/release-plan/{inj['item_id']}/withdraw",
        headers=H,
        json={"reason": "Released early by mistake"},
    )
    assert withdrawn.status_code == 200 and _item(withdrawn.json(), "EVI-INJ-01")["state"] == "withdrawn"
    assert student.get(f"/api/cohorts/{cid}/evidence/EV-006").status_code == 404
    preview = instructor.get(f"/api/cohorts/{cid}/staff/evidence-preview").json()
    assert next(i for i in preview["injects"] if i["code"] == "INJ-01")["released"] is False

    again = instructor.post(f"/api/cohorts/{cid}/release-plan/{inj['item_id']}/release", headers=H, json={})
    assert again.status_code == 200 and _item(again.json(), "EVI-INJ-01")["state"] == "released"
    assert student.get(f"/api/cohorts/{cid}/evidence/EV-006").status_code == 200


def test_answer_keys_unapproved_injects_and_unauthorized_scoring_stay_blocked(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    for code, expected in (
        ("AK-CH-E03-TRIAGE", "staff only"),
        ("EVI-INJ-02", "not been approved"),
        ("CH-K01", "not authorized"),
    ):
        r = instructor.post(
            f"/api/cohorts/{cid}/release-plan/{_item(plan, code)['item_id']}/release", headers=H, json={}
        )
        assert r.status_code == 409 and expected in r.json()["detail"], (code, r.text)


def test_hold_and_resume(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    item = _item(instructor.get(f"/api/cohorts/{cid}/release-plan").json(), "DOC-FRI")
    held = instructor.post(
        f"/api/cohorts/{cid}/release-plan/{item['item_id']}/hold",
        headers=H,
        json={"reason": "Panel room not ready"},
    )
    assert held.status_code == 200 and _item(held.json(), "DOC-FRI")["state"] == "held"
    assert (
        instructor.post(
            f"/api/cohorts/{cid}/release-plan/{item['item_id']}/hold", headers=H, json={}
        ).status_code
        == 409
    )
    resumed = instructor.post(f"/api/cohorts/{cid}/release-plan/{item['item_id']}/resume", headers=H, json={})
    assert resumed.status_code == 200 and _item(resumed.json(), "DOC-FRI")["state"] == "pending"


def test_scheduled_items_open_when_due_and_lesson_stages_drive_documents(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    base = _base_version(editor)
    label = f"3.{next(_seq)}-t{int(time.time()) % 1000}"
    draft = editor.post(
        f"/api/admin/scenario-versions/{base['id']}/clone", headers=H, json={"version_label": label}
    ).json()
    sched = {
        "code": "CH-MON-WARMUP",
        "item_type": "challenge",
        "title": "Monday warm-up",
        "body": "Warm up",
        "trigger_type": "scheduled",
        "trigger_day": "Mon",
        "trigger_time": "09:00",
        "audience": "investigator",
    }
    future = {
        **sched,
        "code": "CH-FRI-LATER",
        "title": "Later",
        "trigger_day": "Fri",
        "trigger_time": "11:00",
    }
    for body in (sched, future):
        assert (
            editor.post(f"/api/admin/scenario-versions/{draft['id']}/items", headers=H, json=body).status_code
            == 201
        )
    assert editor.post(f"/api/admin/scenario-versions/{draft['id']}/submit", headers=H).status_code == 200
    _approve_latest(client, draft["id"])

    # Past cohort: Monday's item is already due and opens on activation. Future cohort: nothing opens yet.
    past = _new_cohort(client, "2026-02-02", "2026-02-06")
    plan = admin.post(
        f"/api/admin/cohorts/{past}/activate-scenario", headers=H, json={"scenario_version_id": draft["id"]}
    ).json()
    assert _item(plan, "CH-MON-WARMUP")["state"] == "released"
    assert _item(plan, "CH-MON-WARMUP")["due_at"].startswith("2026-02-02T15:00")  # 09:00 America/Chicago
    future_cohort = _new_cohort(client, "2030-03-04", "2030-03-08")
    plan2 = admin.post(
        f"/api/admin/cohorts/{future_cohort}/activate-scenario",
        headers=H,
        json={"scenario_version_id": draft["id"]},
    ).json()
    assert (
        _item(plan2, "CH-MON-WARMUP")["state"] == "pending"
        and _item(plan2, "CH-FRI-LATER")["state"] == "pending"
    )

    # Lesson stage → document block (data-driven gate, formerly hard-coded).
    lessons = admin.get(f"/api/staff/cohorts/{past}/lesson-releases").json()
    m04 = next(lesson for lesson in lessons if lesson["module_code"] == "M04")
    r = admin.post(
        f"/api/staff/cohorts/{past}/lesson-releases/{m04['lesson_id']}",
        headers=H,
        json={"lifecycle_state": "released"},
    )
    assert r.status_code == 200, r.text
    plan = admin.get(f"/api/cohorts/{past}/release-plan").json()
    assert _item(plan, "DOC-TUE-EARLY")["state"] == "released"
    assert _item(plan, "DOC-TUE-DISCOVERY")["state"] == "pending"  # gated on "taught", not "released"
    admin.post(
        f"/api/staff/cohorts/{past}/lesson-releases/{m04['lesson_id']}",
        headers=H,
        json={"lifecycle_state": "withdrawn"},
    )
    plan = admin.get(f"/api/cohorts/{past}/release-plan").json()
    assert _item(plan, "DOC-TUE-EARLY")["state"] == "withdrawn"


def test_plan_access_is_role_and_cohort_scoped(client):
    cohorts = _cohort_ids(client)
    demo1, demo2 = cohorts["PACT-DEMO-01"], cohorts["PACT-DEMO-02"]
    assert _as(client, "inv.brooks").get(f"/api/cohorts/{demo1}/release-plan").status_code in (403, 404)
    evaluator = _as(client, "eval.shah")
    view = evaluator.get(f"/api/cohorts/{demo1}/release-plan")
    assert view.status_code == 200 and view.json()["can_control"] is False
    ak = _item(view.json(), "AK-CH-E03-TRIAGE")
    assert "DEVELOPMENT PLACEHOLDER" in ak["preview"]  # staff can read answer keys
    assert (
        evaluator.post(
            f"/api/cohorts/{demo1}/release-plan/{ak['item_id']}/hold", headers=H, json={}
        ).status_code
        == 403
    )
    assert _as(client, "instr.lin").get(f"/api/cohorts/{demo2}/release-plan").status_code == 404
    assert _as(client, "inv.brooks").get("/api/admin/scenario-versions").status_code == 403
    assert _as(client, "instr.lin").get("/api/student/challenges").status_code == 403
