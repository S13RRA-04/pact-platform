"""Scenario release plans (HARBORLINE v0.5): package approval, activation, squad tracks, per-cohort control."""

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
        if v["case_code"] == "HARBORLINE" and v["version_label"] == "0.5"
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
def test_harborline_plan_is_built_from_the_v05_packets(client):
    editor = _as(client, "curr.ortega")
    base = _base_version(editor)
    assert base["approval_status"] == "approved" and base["locked"]
    detail = editor.get(f"/api/admin/scenario-versions/{base['id']}").json()
    codes = {i["code"]: i for i in detail["items"]}
    # One document item per staged packet; its records open with it; every gate is instructor-controlled.
    for n in range(1, 18):
        pkt = codes[f"PKT-{n:02d}"]
        assert pkt["item_type"] == "document" and pkt["document_code"] == f"HBL-{n:02d}"
        assert pkt["trigger_type"] == "manual" and "Release_Register_v0.5" in pkt["instructor_notes"]
    for n in range(1, 17):
        evi = codes[f"EVI-{n:02d}"]
        assert evi["trigger_type"] == "after_item" and evi["trigger_after_code"] == f"PKT-{n:02d}"
    assert "EVI-17" not in codes  # packet 17 is a worksheet with no new records
    # Monday/Tuesday case packets go to one squad; Wednesday search returns to one site team.
    assert [codes[f"PKT-{n:02d}"]["track"] for n in range(1, 9)] == [f"case:{c}" for c in "ABCDABCD"]
    assert [codes[f"PKT-{n}"]["track"] for n in (12, 13, 14)] == ["site:418", "site:R12", "site:C14"]
    assert all(codes[f"PKT-{n:02d}"]["track"] is None for n in (9, 10, 11, 15, 16, 17))
    assert codes["EVI-05"]["track"] == "case:A" and codes["EVI-13"]["track"] == "site:R12"
    # Faculty keys come from the instructor master, staff only.
    for code in ("AK-OVERVIEW", "AK-MON", "AK-TUE", "AK-WED", "AK-THU", "AK-FRI", "AK-GATES", "AK-K01"):
        assert codes[code]["audience"] == "staff" and codes[code]["item_type"] == "answer_key"
    assert codes["AK-TUE"]["body"].startswith("ACT II") and "Calder Venn" in codes["AK-TUE"]["body"]
    assert "Gate 1 Monday" in codes["AK-GATES"]["body"]
    # Student-facing knowledge-check text never carries the key; the staff key does.
    assert "INSTRUCTOR KEY" not in codes["CH-K01"]["body"] and "INSTRUCTOR KEY" in codes["AK-K01"]["body"]
    assert codes["CH-K02"]["scored"] and codes["CH-K02"]["instrument_code"] == "K02"
    # v0.3 material is reference only now.
    assert not any(c.startswith(("PKT-E", "AK-E", "DOC-")) for c in codes)
    assert codes["EVI-LAB"]["trigger_type"] == "manual"


def test_records_carry_the_packet_wording_and_faculty_cautions(client):
    """Evidence text is the packet's own row; staff previews carry the master's caution for the record."""
    cid = _cohort_ids(client)["PACT-DEMO-01"]
    instructor = _as(client, "instr.lin")
    preview = instructor.get(f"/api/cohorts/{cid}/staff/evidence-preview")
    assert preview.status_code == 200, preview.text
    items = {e["code"]: e for e in preview.json()["evidence"]}
    assert items["S-418-01"]["track"] == "site:418" and items["HX-COORD-01"]["track"] is None
    pc01 = items["PC-01"]
    assert "Calder Venn was assigned KMS-KEY-67" in pc01["content"]
    assert pc01["limitations"].startswith("Assigned device")
    assert "token could have been shared or compromised" in pc01["instructor_notes"]
    assert "Device association" in pc01["instructor_notes"]  # continuity register "do not overstate"
    # The locked H- records keep their own observation and raw lines, one record per ID.
    assert {"H-EDR-01", "H-IAM-01"} <= set(items)
    assert items["X-A-01"]["observed_as_recorded"].startswith("24 Oct 22:11:50Z")


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


def test_earlier_scenarios_are_retired_and_activation_rules_hold(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    versions = editor.get("/api/admin/scenario-versions").json()
    assert all(v["case_code"] != "GLASS-HARBOR" or v["approval_status"] == "retired" for v in versions)
    assert all(
        v["approval_status"] == "retired"
        for v in versions
        if v["case_code"] == "HARBORLINE" and v["version_label"] == "0.3"
    )
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
    instructor, student = _as(client, "instr.reyes"), _as(client, "inv.harper")  # squad Alpha: case A
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    assert _item(plan, "PKT-05")["state"] == "pending"
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 404

    # Records wait for their packet; releasing the packet opens them.
    early = _act(instructor, cid, plan, "EVI-05", "release")
    assert early.status_code == 409 and "Waiting for PKT-05" in early.json()["detail"]
    released = _act(instructor, cid, plan, "PKT-05", "release")
    assert released.status_code == 200, released.text
    assert _item(released.json(), "EVI-05")["state"] == "released"
    evidence = student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01")
    assert evidence.status_code == 200
    body = evidence.json()
    assert (
        body["observed_as_recorded"].startswith("2026-10-25T04:09:03Z")
        and "network_events.csv" in body["content"]
    )
    assert "Collector, export method and custody chain are not stated" in body["provenance"]
    titles = {n["title"] for n in student.get("/api/student/notifications").json()}
    assert {"New case evidence", "New course document"} <= titles

    assert _act(instructor, cid, plan, "EVI-05", "withdraw").status_code == 422  # reason required
    withdrawn = _act(instructor, cid, plan, "EVI-05", "withdraw", "Released early by mistake")
    assert withdrawn.status_code == 200 and _item(withdrawn.json(), "EVI-05")["state"] == "withdrawn"
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 404
    assert _act(instructor, cid, plan, "EVI-05", "release").status_code == 200
    assert student.get(f"/api/cohorts/{cid}/evidence/H-PXY-01").status_code == 200


def test_squad_tracks_keep_each_case_with_its_squad(client):
    """Monday/Tuesday case packets reach only their squad; search returns only their site team (Gate 1)."""
    cid = _cohort_ids(client)["PACT-DEMO-01"]
    instructor = _as(client, "instr.lin")
    alpha, bravo = _as(client, "inv.brooks"), _as(client, "inv.patel")  # Alpha: A/418; Bravo: B/R12
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    for code in ("PKT-02", "PKT-12"):
        if _item(plan, code)["state"] != "released":
            assert _act(instructor, cid, plan, code, "release").status_code == 200

    # Case B's records and packet: Bravo yes, Alpha no (no listing, no record, no link, no citation).
    assert bravo.get(f"/api/cohorts/{cid}/evidence/B-WIRE-01").status_code == 200
    assert alpha.get(f"/api/cohorts/{cid}/evidence/B-WIRE-01").status_code == 404
    assert all(e["code"] != "B-WIRE-01" for e in alpha.get(f"/api/cohorts/{cid}/evidence").json())
    case = alpha.get(f"/api/cohorts/{cid}/case").json()
    assert all(u["code"] != "INJ-02" for u in case["updates"])
    assert all(t["evidence_code"] != "B-WIRE-01" for t in case["timeline"])
    doc_id = _sql("SELECT max(id) FROM curriculum_documents WHERE document_code = 'HBL-02'").scalar()
    assert "HBL-02" in {m["document_code"] for m in bravo.get("/api/student/materials").json()}
    assert "HBL-02" not in {m["document_code"] for m in alpha.get("/api/student/materials").json()}
    assert alpha.post(f"/api/materials/{doc_id}/download-link", headers=H).status_code == 404
    assignment = alpha.get("/api/student/dashboard").json()["assignments"][0]
    assert "B-WIRE-01" not in alpha.get(f"/api/assignments/{assignment['id']}").json()["available_evidence"]
    cited = alpha.put(
        f"/api/assignments/{assignment['id']}/draft",
        headers=H,
        json={"content": {}, "cited_evidence": ["B-WIRE-01"]},
    )
    assert cited.status_code in (409, 422)  # 409 if this persona already submitted

    # Suite 418 search return: Alpha's site team only.
    assert alpha.get(f"/api/cohorts/{cid}/evidence/S-418-01").status_code == 200
    assert bravo.get(f"/api/cohorts/{cid}/evidence/S-418-01").status_code == 404
    # Staff see every track.
    assert instructor.get(f"/api/cohorts/{cid}/evidence/B-WIRE-01").status_code == 200

    # Re-assigning a squad's track moves access with it (and is audited); restore afterwards.
    squads = instructor.get(f"/api/cohorts/{cid}/squads").json()["squads"]
    bravo_squad = next(sq for sq in squads if sq["name"] == "Bravo")
    url = f"/api/cohorts/{cid}/squads/{bravo_squad['id']}"
    bad = instructor.patch(url, headers=H, json={"name": "Bravo", "case_track": "bad track"})
    assert bad.status_code == 422
    assert alpha.patch(url, headers=H, json={"name": "Bravo"}).status_code in (403, 404)
    moved = instructor.patch(url, headers=H, json={"name": "Bravo", "case_track": "A", "site_team": "R12"})
    assert moved.status_code == 200, moved.text
    assert bravo.get(f"/api/cohorts/{cid}/evidence/B-WIRE-01").status_code == 404
    restored = instructor.patch(url, headers=H, json={"name": "Bravo", "case_track": "b", "site_team": "r12"})
    assert next(sq for sq in restored.json()["squads"] if sq["name"] == "Bravo")["case_track"] == "B"
    assert bravo.get(f"/api/cohorts/{cid}/evidence/B-WIRE-01").status_code == 200
    assert _sql("SELECT count(*) FROM audit_events WHERE action = 'squad.update'").scalar() >= 2


def test_undated_records_stay_out_of_the_timeline(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor, student = _as(client, "instr.reyes"), _as(client, "inv.harper")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    if _item(plan, "PKT-09")["state"] != "released":
        assert _act(instructor, cid, plan, "PKT-09", "release").status_code == 200
    directive = student.get(f"/api/cohorts/{cid}/evidence/HX-COORD-01").json()
    assert directive["observed_at"] is None and directive["observed_as_recorded"] == "Not recorded in source"
    timeline = student.get(f"/api/cohorts/{cid}/case").json()["timeline"]
    assert all(t["evidence_code"] != "HX-COORD-01" for t in timeline)


def test_answer_keys_and_unauthorized_scoring_stay_blocked(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    for code, expected in (("AK-TUE", "staff only"), ("CH-K01", "not authorized")):
        r = _act(instructor, cid, plan, code, "release")
        assert r.status_code == 409 and expected in r.json()["detail"], (code, r.text)


def test_hold_and_resume(client):
    cid = _cohort_ids(client)["PACT-DEMO-02"]
    instructor = _as(client, "instr.reyes")
    plan = instructor.get(f"/api/cohorts/{cid}/release-plan").json()
    held = _act(instructor, cid, plan, "PKT-16", "hold", "Panel room not ready")
    assert held.status_code == 200 and _item(held.json(), "PKT-16")["state"] == "held"
    assert _act(instructor, cid, plan, "PKT-16", "hold").status_code == 409
    resumed = _act(instructor, cid, plan, "PKT-16", "resume")
    assert resumed.status_code == 200 and _item(resumed.json(), "PKT-16")["state"] == "pending"


def test_triggers_cascades_and_cloned_injects_need_their_own_approval(client):
    editor, admin = _as(client, "curr.ortega"), _as(client, "admin.novak")
    draft = _clone(client, "3")
    url = f"/api/admin/scenario-versions/{draft['id']}/items"
    squad_a = {
        "code": "CH-SQUAD-A",
        "item_type": "challenge",
        "title": "Case A only",
        "body": "Squad A task",
        "trigger_type": "after_item",
        "trigger_after_code": "PKT-09",
        "track": "case:a",
    }
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
            "trigger_after_code": "PKT-09",
        },
        {
            "code": "CH-M04",
            "item_type": "debrief",
            "title": "M04 debrief",
            "body": "Debrief",
            "trigger_type": "lesson_gate",
            "trigger_module_code": "M04",
            "trigger_lesson_state": "taught",
        },
        squad_a,
    ):
        assert editor.post(url, headers=H, json=body).status_code == 201, body["code"]
    assert (
        editor.post(url, headers=H, json={**squad_a, "code": "CH-BAD", "track": "squad:A"}).status_code == 422
    )
    _submit_and_approve(client, draft)

    past = _new_cohort(client, "2026-02-02", "2026-02-06")
    plan = admin.post(
        f"/api/admin/cohorts/{past}/activate-scenario", headers=H, json={"scenario_version_id": draft["id"]}
    ).json()
    assert _item(plan, "CH-MON-WARMUP")["state"] == "released"
    assert _item(plan, "CH-MON-WARMUP")["due_at"].startswith("2026-02-02T15:00")  # 09:00 America/Chicago
    assert _item(plan, "CH-SQUAD-A")["track"] == "case:A"
    future = _new_cohort(client, "2030-03-04", "2030-03-08")
    plan2 = admin.post(
        f"/api/admin/cohorts/{future}/activate-scenario", headers=H, json={"scenario_version_id": draft["id"]}
    ).json()
    assert _item(plan2, "CH-MON-WARMUP")["state"] == "pending"

    # Packet -> its records and the dependent challenges open automatically. Cloned injects are drafts: the
    # plan is approved but the evidence content is not, so the records are blocked with a reason.
    released = _act(admin, past, plan, "PKT-09", "release")
    assert released.status_code == 200, released.text
    plan = released.json()
    assert _item(plan, "CH-AFTER-PKT")["state"] == "released"
    assert _item(plan, "CH-SQUAD-A")["state"] == "released"
    assert _item(plan, "EVI-09")["state"] == "pending"
    assert "not been approved" in _item(plan, "EVI-09")["blocked_reason"]

    # Lesson stage -> gated item.
    lessons = admin.get(f"/api/staff/cohorts/{past}/lesson-releases").json()
    m04 = next(lesson for lesson in lessons if lesson["module_code"] == "M04")
    for state in ("released", "taught"):
        assert (
            admin.post(
                f"/api/staff/cohorts/{past}/lesson-releases/{m04['lesson_id']}",
                headers=H,
                json={"lifecycle_state": state},
            ).status_code
            == 200
        )
    assert _item(admin.get(f"/api/cohorts/{past}/release-plan").json(), "CH-M04")["state"] == "released"

    # A student without a squad sees untracked material only (fails closed for squad-tracked items).
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
    assert "HBL-09" in codes
    challenges = {c["code"] for c in student.get("/api/student/challenges").json()}
    assert {"CH-MON-WARMUP", "CH-AFTER-PKT", "CH-M04"} <= challenges
    assert "CH-SQUAD-A" not in challenges
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
    ak = _item(view.json(), "AK-TUE")
    assert ak["preview"].startswith("ACT II")  # staff can read faculty keys
    assert (
        evaluator.post(
            f"/api/cohorts/{demo1}/release-plan/{ak['item_id']}/hold", headers=H, json={}
        ).status_code
        == 403
    )
    assert _as(client, "instr.lin").get(f"/api/cohorts/{demo2}/release-plan").status_code == 404
    assert _as(client, "inv.brooks").get("/api/admin/scenario-versions").status_code == 403
    assert _as(client, "instr.lin").get("/api/student/challenges").status_code == 403
