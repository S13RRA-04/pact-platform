"""Local accounts with mandatory TOTP, and user/cohort/squad administration."""

from __future__ import annotations

import itertools
import time

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app.config import Settings
from app.db import get_engine

H = {"X-PACT-Request": "1"}
PASSWORD = "correct horse battery staple 42"
_seq = itertools.count(1)


def _client(client: TestClient) -> TestClient:
    """Separate cookie jar sharing the app (and its test DB overrides)."""
    return TestClient(client.app)


def _admin(client: TestClient) -> TestClient:
    c = _client(client)
    assert c.post("/api/dev/login", json={"username": "admin.novak"}, headers=H).status_code == 200
    return c


def _persona(client: TestClient, username: str) -> TestClient:
    c = _client(client)
    assert c.post("/api/dev/login", json={"username": username}, headers=H).status_code == 200
    return c


def make_account(client: TestClient, roles: list[str] | None = None) -> dict:
    admin = _admin(client)
    username = f"local.user{next(_seq)}{int(time.time()) % 100000}"
    created = admin.post(
        "/api/admin/users",
        headers=H,
        json={
            "username": username,
            "display_name": f"Local User {username}",
            "email": f"{username}@pact-training.example",
            "global_roles": roles or [],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["credential_state"] == "not_set_up"
    link = admin.post(
        f"/api/admin/users/{created.json()['id']}/setup-link", headers=H, json={"purpose": "enroll"}
    )
    assert link.status_code == 200, link.text
    token = link.json()["setup_path"].split("token=", 1)[1]
    anon = _client(client)
    started = anon.post("/api/auth/setup/start", headers=H, json={"token": token})
    assert started.status_code == 200, started.text
    secret = started.json()["totp_secret"]
    done = anon.post(
        "/api/auth/setup/complete",
        headers=H,
        json={"token": token, "password": PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert done.status_code == 204, done.text
    return {"id": created.json()["id"], "username": username, "secret": secret, "token": token}


def _next_code(secret: str) -> str:
    # The enrollment code consumed the current step; the next step is within the accepted window.
    return pyotp.TOTP(secret).at(time.time() + 30)


def local_login(client: TestClient, account: dict) -> TestClient:
    c = _client(client)
    assert (
        c.post(
            "/api/auth/login", headers=H, json={"username": account["username"], "password": PASSWORD}
        ).status_code
        == 200
    )
    r = c.post("/api/auth/mfa", headers=H, json={"code": _next_code(account["secret"])})
    assert r.status_code == 204, r.text
    return c


# --- sign-in ---------------------------------------------------------------------------------------
def test_full_setup_and_two_step_login(client):
    account = make_account(client)
    c = _client(client)
    wrong = c.post(
        "/api/auth/login", headers=H, json={"username": account["username"], "password": "nope" * 4}
    )
    unknown = c.post("/api/auth/login", headers=H, json={"username": "no.such.user", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # no username enumeration

    assert (
        c.post(
            "/api/auth/login", headers=H, json={"username": account["username"].upper(), "password": PASSWORD}
        ).status_code
        == 200
    )
    assert c.get("/api/me").status_code == 401  # password alone authorizes nothing
    assert c.post("/api/auth/mfa", headers=H, json={"code": "000000"}).status_code == 401
    assert c.post("/api/auth/mfa", headers=H, json={"code": _next_code(account["secret"])}).status_code == 204
    me = c.get("/api/me")
    assert me.status_code == 200 and me.json()["identity_provider"] == "local"

    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").status_code == 401


def test_totp_code_cannot_be_replayed(client):
    account = make_account(client)
    local_login(client, account)
    c = _client(client)
    assert (
        c.post(
            "/api/auth/login", headers=H, json={"username": account["username"], "password": PASSWORD}
        ).status_code
        == 200
    )
    assert c.post("/api/auth/mfa", headers=H, json={"code": _next_code(account["secret"])}).status_code == 401


def test_lockout_and_security_admin_unlock(client):
    account = make_account(client)
    c = _client(client)
    for _ in range(5):
        c.post(
            "/api/auth/login",
            headers=H,
            json={"username": account["username"], "password": "wrong-password!"},
        )
    blocked = c.post(
        "/api/auth/login", headers=H, json={"username": account["username"], "password": PASSWORD}
    )
    assert blocked.status_code == 401  # locked even with the right password
    secops = _persona(client, "secops.kim")
    users = {u["username"]: u for u in secops.get("/api/admin/users").json()}
    assert users[account["username"]]["credential_state"] == "locked"
    assert secops.post(f"/api/admin/users/{account['id']}/unlock", headers=H).status_code == 200
    local_login(client, account)


def test_setup_link_is_single_use_and_reset_disables_old_credentials(client):
    account = make_account(client)
    anon = _client(client)
    assert anon.post("/api/auth/setup/start", headers=H, json={"token": account["token"]}).status_code == 410

    session = local_login(client, account)
    assert session.get("/api/me").status_code == 200
    admin = _admin(client)
    reset = admin.post(f"/api/admin/users/{account['id']}/setup-link", headers=H, json={"purpose": "reset"})
    assert reset.status_code == 200
    assert session.get("/api/me").status_code == 401  # all sessions ended by the reset
    old = _client(client).post(
        "/api/auth/login", headers=H, json={"username": account["username"], "password": PASSWORD}
    )
    assert old.status_code == 401  # previous password disabled immediately


def test_weak_password_and_bad_code_rejected_at_setup(client):
    admin = _admin(client)
    username = f"weak.user{next(_seq)}"
    uid = admin.post(
        "/api/admin/users",
        headers=H,
        json={"username": username, "display_name": "Weak", "email": f"{username}@pact-training.example"},
    ).json()["id"]
    token = (
        admin.post(f"/api/admin/users/{uid}/setup-link", headers=H, json={})
        .json()["setup_path"]
        .split("=")[1]
    )
    anon = _client(client)
    secret = anon.post("/api/auth/setup/start", headers=H, json={"token": token}).json()["totp_secret"]
    short = anon.post(
        "/api/auth/setup/complete",
        headers=H,
        json={"token": token, "password": "short", "totp_code": pyotp.TOTP(secret).now()},
    )
    assert short.status_code == 422
    has_name = anon.post(
        "/api/auth/setup/complete",
        headers=H,
        json={"token": token, "password": f"{username}-long-enough", "totp_code": pyotp.TOTP(secret).now()},
    )
    assert has_name.status_code == 422
    bad_code = anon.post(
        "/api/auth/setup/complete",
        headers=H,
        json={"token": token, "password": PASSWORD, "totp_code": "123456"},
    )
    assert bad_code.status_code == 422


def test_deactivation_revokes_sessions(client):
    account = make_account(client)
    session = local_login(client, account)
    admin = _admin(client)
    assert (
        admin.patch(f"/api/admin/users/{account['id']}", headers=H, json={"active": False}).status_code == 200
    )
    assert session.get("/api/me").status_code == 401


def test_password_change_requires_current_password_and_ends_other_sessions(client):
    account = make_account(client)
    first = local_login(client, account)
    other = _client(client)
    assert (
        other.post(
            "/api/auth/login", headers=H, json={"username": account["username"], "password": PASSWORD}
        ).status_code
        == 200
    )
    bad = first.post(
        "/api/auth/password",
        headers=H,
        json={"current_password": "not-it-at-all", "new_password": "a brand new passphrase 9"},
    )
    assert bad.status_code == 403
    ok = first.post(
        "/api/auth/password",
        headers=H,
        json={"current_password": PASSWORD, "new_password": "a brand new passphrase 9"},
    )
    assert ok.status_code == 204
    assert first.get("/api/me").status_code == 200  # the session that changed it stays
    with get_engine(Settings().test_database_url).connect() as conn:
        live = conn.scalar(
            text("SELECT count(*) FROM auth_sessions WHERE user_id = :u AND revoked_at IS NULL"),
            {"u": account["id"]},
        )
        reasons = set(
            conn.scalars(
                text("SELECT revoked_reason FROM auth_sessions WHERE user_id = :u"), {"u": account["id"]}
            )
        )
    assert live == 1 and "password_changed" in reasons  # every other session ended


# --- authorization boundaries ------------------------------------------------------------------------
def test_only_program_admin_manages_users_and_cohorts(client):
    body = {"username": "should.not.exist", "display_name": "X", "email": "x@pact-training.example"}
    for persona in ("inv.brooks", "instr.lin", "secops.kim", "curr.ortega"):
        c = _persona(client, persona)
        assert c.post("/api/admin/users", headers=H, json=body).status_code == 403, persona
        assert (
            c.post(
                "/api/admin/cohorts",
                headers=H,
                json={"code": "NOPE-01", "name": "x", "start_date": "2027-01-04", "end_date": "2027-01-08"},
            ).status_code
            == 403
        )
    assert _persona(client, "inv.brooks").get("/api/admin/users").status_code == 403
    assert _persona(client, "secops.kim").get("/api/admin/users").status_code == 200


def test_admin_cannot_lock_themselves_out(client):
    admin = _admin(client)
    me = admin.get("/api/me").json()
    assert admin.patch(f"/api/admin/users/{me['id']}", headers=H, json={"active": False}).status_code == 409
    assert admin.put(f"/api/admin/users/{me['id']}/roles", headers=H, json={"roles": []}).status_code == 409


def test_mutations_require_csrf_header(client):
    admin = _admin(client)
    assert (
        admin.post(
            "/api/admin/cohorts",
            json={"code": "CSRF-01", "name": "x", "start_date": "2027-01-04", "end_date": "2027-01-08"},
        ).status_code
        == 403
    )


# --- cohorts and enrollment ---------------------------------------------------------------------------
def test_cohort_lifecycle_and_enrollment_rules(client):
    admin = _admin(client)
    code = f"TEST-{next(_seq):02d}{int(time.time()) % 1000}"
    assert (
        admin.post(
            "/api/admin/cohorts",
            headers=H,
            json={
                "code": code,
                "name": "Bad TZ",
                "start_date": "2027-01-04",
                "end_date": "2027-01-08",
                "timezone": "Mars/Olympus",
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/admin/cohorts",
            headers=H,
            json={"code": code, "name": "Backwards", "start_date": "2027-01-08", "end_date": "2027-01-04"},
        ).status_code
        == 422
    )
    created = admin.post(
        "/api/admin/cohorts",
        headers=H,
        json={
            "code": code.lower(),
            "name": "Test cohort",
            "start_date": "2027-01-04",
            "end_date": "2027-01-08",
        },
    )
    assert created.status_code == 201, created.text
    cohort = created.json()
    assert cohort["code"] == code
    assert (
        admin.post(
            "/api/admin/cohorts",
            headers=H,
            json={"code": code, "name": "dup", "start_date": "2027-01-04", "end_date": "2027-01-08"},
        ).status_code
        == 409
    )

    account = make_account(client)
    members = f"/api/admin/cohorts/{cohort['id']}/members"
    assert (
        admin.post(members, headers=H, json={"user_id": account["id"], "role": "student"}).status_code == 422
    )
    assert (
        admin.post(
            members, headers=H, json={"user_id": account["id"], "role": "instructor", "pathway": "analyst"}
        ).status_code
        == 422
    )
    enrolled = admin.post(
        members, headers=H, json={"user_id": account["id"], "role": "student", "pathway": "analyst"}
    )
    assert enrolled.status_code == 200
    assert (
        admin.post(members, headers=H, json={"user_id": account["id"], "role": "evaluator"}).status_code
        == 409
    )

    updated = admin.patch(f"/api/admin/cohorts/{cohort['id']}", headers=H, json={"status": "archived"})
    assert updated.status_code == 200 and updated.json()["status"] == "archived"


def test_pathway_locked_after_submission_and_withdrawal_removes_access(client):
    admin = _admin(client)
    cohort_id = next(c["id"] for c in admin.get("/api/admin/cohorts").json() if c["code"] == "PACT-DEMO-01")
    account = make_account(client)
    detail = admin.post(
        f"/api/admin/cohorts/{cohort_id}/members",
        headers=H,
        json={"user_id": account["id"], "role": "student", "pathway": "investigator"},
    ).json()
    membership = next(m for m in detail["members"] if m["user_id"] == account["id"])

    student = local_login(client, account)
    dashboard = student.get("/api/student/dashboard")
    assert dashboard.status_code == 200
    assignment = dashboard.json()["assignments"][0]
    assert assignment["pathway"] == "investigator"
    saved = student.put(
        f"/api/assignments/{assignment['id']}/draft",
        headers=H,
        json={
            "content": {"preservation": "Preserve the native cloud audit export with a hash manifest."},
            "cited_evidence": ["EV-002"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert student.post(f"/api/assignments/{assignment['id']}/submit", headers=H).status_code == 200

    member_url = f"/api/admin/cohorts/{cohort_id}/members/{membership['membership_id']}"
    assert admin.patch(member_url, headers=H, json={"pathway": "analyst"}).status_code == 409

    squad_id = next(s["id"] for s in detail["squads"] if s["name"] == "Alpha")
    squad_members = next(s["member_ids"] for s in detail["squads"] if s["id"] == squad_id)
    instructor = _persona(client, "instr.lin")
    assert (
        instructor.put(
            f"/api/cohorts/{cohort_id}/squads/{squad_id}/members",
            headers=H,
            json={"user_ids": [*squad_members, account["id"]]},
        ).status_code
        == 200
    )

    withdrawn = admin.patch(member_url, headers=H, json={"status": "withdrawn"})
    assert withdrawn.status_code == 200
    assert account["id"] not in next(
        s["member_ids"] for s in withdrawn.json()["squads"] if s["id"] == squad_id
    )
    assert student.get("/api/student/dashboard").status_code == 403
    # Access ends, but the enrollment and submission are retained for staff review and audit.
    assert student.get(f"/api/assignments/{assignment['id']}").status_code == 404


def test_instructor_squad_management_is_cohort_scoped(client):
    instructor = _persona(client, "instr.lin")
    admin = _admin(client)
    cohorts = {c["code"]: c["id"] for c in admin.get("/api/admin/cohorts").json()}
    own, other = cohorts["PACT-DEMO-01"], cohorts["PACT-DEMO-02"]
    name = f"Charlie{next(_seq)}"
    created = instructor.post(f"/api/cohorts/{own}/squads", headers=H, json={"name": name})
    assert created.status_code == 201
    squad = next(s for s in created.json()["squads"] if s["name"] == name)
    assert instructor.post(f"/api/cohorts/{other}/squads", headers=H, json={"name": "X"}).status_code == 404
    staff_id = next(m["user_id"] for m in created.json()["members"] if m["role"] == "instructor")
    assert (
        instructor.put(
            f"/api/cohorts/{own}/squads/{squad['id']}/members", headers=H, json={"user_ids": [staff_id]}
        ).status_code
        == 422
    )
    assert instructor.delete(f"/api/cohorts/{own}/squads/{squad['id']}", headers=H).status_code == 200
    assert (
        _persona(client, "inv.brooks")
        .post(f"/api/cohorts/{own}/squads", headers=H, json={"name": "Nope"})
        .status_code
        == 403
    )


# --- configuration --------------------------------------------------------------------------------
def test_production_requires_totp_key_and_secure_cookie():
    base = {
        "env": "production",
        "session_secret": "x" * 48,
        "object_storage_provider": "r2",
        "r2_endpoint_url": "https://r2.invalid",
        "r2_bucket": "b",
        "r2_access_key_id": "k",
        "r2_secret_access_key": "s",
        "clamav_host": "clamav",
    }
    with pytest.raises(ValidationError, match="TOTP_ENCRYPTION_KEY"):
        Settings(**base, cookie_secure=True)
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(**base, totp_encryption_key="k" * 44)


def test_cohort_code_can_be_edited_with_validation_and_audit(client):
    admin = _admin(client)
    stamp = f"{next(_seq):02d}{int(time.time()) % 10000}"
    created = admin.post(
        "/api/admin/cohorts",
        headers=H,
        json={
            "code": f"RENAME-{stamp}",
            "name": "Rename me",
            "start_date": "2027-03-01",
            "end_date": "2027-03-05",
        },
    )
    assert created.status_code == 201
    cid = created.json()["id"]

    renamed = admin.patch(f"/api/admin/cohorts/{cid}", headers=H, json={"code": f"pact-27-{stamp}"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["code"] == f"PACT-27-{stamp}"  # normalized to upper case
    assert admin.patch(f"/api/admin/cohorts/{cid}", headers=H, json={"code": "bad code!"}).status_code == 422
    assert (
        admin.patch(f"/api/admin/cohorts/{cid}", headers=H, json={"code": "PACT-DEMO-01"}).status_code == 409
    )
    assert (
        admin.patch(f"/api/admin/cohorts/{cid}", headers=H, json={"code": f"PACT-27-{stamp}"}).status_code
        == 200
    )
    assert (
        _persona(client, "instr.lin")
        .patch(f"/api/admin/cohorts/{cid}", headers=H, json={"code": "INSTR-01"})
        .status_code
        == 403
    )

    with get_engine(Settings().test_database_url).connect() as conn:
        details = conn.scalar(
            text(
                "SELECT details FROM audit_events WHERE action = 'cohort.update' AND entity_id = :c "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"c": str(cid)},
        )
    assert details["code"] == {"from": f"RENAME-{stamp}", "to": f"PACT-27-{stamp}"}
