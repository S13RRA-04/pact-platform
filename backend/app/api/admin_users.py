"""User, cohort, enrollment and squad administration.

Authority (decided 2026-11-17):
- Program Administrator: create/edit/deactivate users, assign global roles, issue setup/reset links,
  create/edit cohorts, enroll and withdraw members, manage squads.
- Security/Operations Administrator: read users, unlock accounts, revoke sessions.
- Instructor: manage squads in cohorts they teach.
Safeguards: an administrator cannot deactivate themselves or remove their own Program Administrator
role; a user cannot be both a student and staff in the same cohort; a student's pathway cannot change
once they have submitted work; withdrawn memberships are retained, never deleted.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    Cohort,
    CohortMembership,
    CourseVersion,
    Handoff,
    Squad,
    SquadMember,
    Submission,
    User,
    UserRole,
)
from app.schemas.accounts import (
    CohortAdminOut,
    CohortCreateIn,
    CohortDetailOut,
    CohortRoleOut,
    CohortUpdateIn,
    MemberIn,
    MemberOut,
    MemberUpdateIn,
    RolesIn,
    SetupLinkIn,
    SetupLinkOut,
    SquadAdminOut,
    SquadIn,
    SquadMembersIn,
    UserAdminOut,
    UserCreateIn,
    UserUpdateIn,
)
from app.security import session as sess
from app.security.authz import (
    Principal,
    get_principal,
    require_cohort_role,
    require_csrf_header,
    require_global_role,
)
from app.services import accounts

router = APIRouter(
    prefix="/api/admin", tags=["user-administration"], dependencies=[Depends(require_csrf_header)]
)
squad_router = APIRouter(
    prefix="/api/cohorts/{cohort_id}/squads", tags=["squads"], dependencies=[Depends(require_csrf_header)]
)

ADMIN = {"program_admin"}
USER_READERS = {"program_admin", "secops_admin"}
ACCOUNT_SUPPORT = {"program_admin", "secops_admin"}
EMAIL_SYNTHETIC_NOTICE = "Synthetic/training use only."


# --- helpers ------------------------------------------------------------------------------------
def _user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _cohort_or_404(db: Session, cohort_id: int) -> Cohort:
    cohort = db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cohort not found")
    return cohort


def _user_out(db: Session, user: User) -> UserAdminOut:
    rows = db.execute(
        select(CohortMembership, Cohort.code)
        .join(Cohort, Cohort.id == CohortMembership.cohort_id)
        .where(CohortMembership.user_id == user.id)
        .order_by(Cohort.code, CohortMembership.role)
    ).all()
    return UserAdminOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        active=user.active,
        is_synthetic=user.is_synthetic,
        is_dev_persona=user.is_dev_persona,
        global_roles=sorted(r.role for r in user.roles),
        cohort_roles=[
            CohortRoleOut(
                membership_id=m.id,
                cohort_id=m.cohort_id,
                cohort_code=code,
                role=m.role,
                pathway=m.pathway,
                status=m.status,
            )
            for m, code in rows
        ],
        **accounts.account_state(db, user),  # type: ignore[arg-type]
    )


def _check_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown timezone '{tz}'") from exc


def _has_submissions(db: Session, cohort_id: int, user_id: int) -> bool:
    return (
        db.scalar(
            select(Submission.id)
            .where(Submission.cohort_id == cohort_id, Submission.student_id == user_id)
            .limit(1)
        )
        is not None
    )


def _cohort_out(db: Session, cohort: Cohort) -> CohortAdminOut:
    cv = db.get(CourseVersion, cohort.course_version_id)
    counts = dict(
        db.execute(
            select(CohortMembership.role, func.count())
            .where(CohortMembership.cohort_id == cohort.id, CohortMembership.status == "active")
            .group_by(CohortMembership.role)
        ).all()
    )
    return CohortAdminOut(
        id=cohort.id,
        code=cohort.code,
        name=cohort.name,
        start_date=cohort.start_date,
        end_date=cohort.end_date,
        timezone=cohort.timezone,
        status=cohort.status,
        course_version=cv.version_label if cv else "—",
        counts={r: int(counts.get(r, 0)) for r in ("student", "instructor", "evaluator")},
    )


def _cohort_detail(db: Session, cohort: Cohort) -> CohortDetailOut:
    squads = list(db.scalars(select(Squad).where(Squad.cohort_id == cohort.id).order_by(Squad.name)))
    squad_of: dict[int, Squad] = {}
    squad_members: dict[int, list[int]] = {s.id: [] for s in squads}
    for sm in db.scalars(select(SquadMember).where(SquadMember.squad_id.in_([s.id for s in squads] or [0]))):
        squad_members[sm.squad_id].append(sm.user_id)
        squad_of[sm.user_id] = next(s for s in squads if s.id == sm.squad_id)
    rows = db.execute(
        select(CohortMembership, User)
        .join(User, User.id == CohortMembership.user_id)
        .where(CohortMembership.cohort_id == cohort.id)
        .order_by(CohortMembership.status, CohortMembership.role, User.display_name)
    ).all()
    members = [
        MemberOut(
            membership_id=m.id,
            user_id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=m.role,
            pathway=m.pathway,
            status=m.status,
            squad_id=squad_of[u.id].id if m.role == "student" and u.id in squad_of else None,
            squad_name=squad_of[u.id].name if m.role == "student" and u.id in squad_of else None,
            has_submissions=m.role == "student" and _has_submissions(db, cohort.id, u.id),
        )
        for m, u in rows
    ]
    return CohortDetailOut(
        **_cohort_out(db, cohort).model_dump(),
        members=members,
        squads=[SquadAdminOut(id=s.id, name=s.name, member_ids=sorted(squad_members[s.id])) for s in squads],
    )


# --- users --------------------------------------------------------------------------------------
@router.get("/users", response_model=list[UserAdminOut])
def list_users(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[UserAdminOut]:
    require_global_role(db, principal, USER_READERS, "admin.users")
    return [_user_out(db, u) for u in db.scalars(select(User).order_by(User.display_name))]


@router.post("/users", response_model=UserAdminOut, status_code=201)
def create_user(
    body: UserCreateIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> UserAdminOut:
    require_global_role(db, principal, ADMIN, "user.create")
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    user = User(
        username=body.username,
        display_name=body.display_name.strip(),
        email=str(body.email).lower(),
        is_synthetic=True,
        is_dev_persona=False,
        persona_label=None,
        active=True,
    )
    user.roles = [UserRole(role=r) for r in sorted(set(body.global_roles))]
    db.add(user)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        details={"username": user.username, "global_roles": sorted(set(body.global_roles))},
    )
    db.commit()
    return _user_out(db, user)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    body: UserUpdateIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> UserAdminOut:
    require_global_role(db, principal, ADMIN, "user.update")
    user = _user_or_404(db, user_id)
    changes: dict[str, object] = {}
    if body.display_name is not None and body.display_name.strip() != user.display_name:
        user.display_name = changes["display_name"] = body.display_name.strip()
    if body.email is not None and str(body.email).lower() != user.email:
        user.email = changes["email"] = str(body.email).lower()
    if body.active is not None and body.active != user.active:
        if not body.active and user.id == principal.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate your own account")
        user.active = changes["active"] = body.active
        if not body.active:
            changes["sessions_revoked"] = sess.revoke_all_for_user(db, user.id, "account_deactivated")
    if changes:
        audit.record(
            db,
            actor_id=principal.id,
            action="user.update",
            entity_type="user",
            entity_id=user.id,
            details=changes,
        )
        db.commit()
    return _user_out(db, user)


@router.put("/users/{user_id}/roles", response_model=UserAdminOut)
def set_roles(
    user_id: int, body: RolesIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> UserAdminOut:
    require_global_role(db, principal, ADMIN, "user.roles")
    user = _user_or_404(db, user_id)
    wanted = set(body.roles)
    if user.id == principal.id and "program_admin" not in wanted:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove your own Program Administrator role")
    before = {r.role for r in user.roles}
    if wanted != before:
        user.roles = [r for r in user.roles if r.role in wanted] + [
            UserRole(role=r) for r in sorted(wanted - before)
        ]
        audit.record(
            db,
            actor_id=principal.id,
            action="user.roles",
            entity_type="user",
            entity_id=user.id,
            details={"added": sorted(wanted - before), "removed": sorted(before - wanted)},
        )
        db.commit()
        db.refresh(user)
    return _user_out(db, user)


@router.post("/users/{user_id}/setup-link", response_model=SetupLinkOut)
def setup_link(
    user_id: int,
    body: SetupLinkIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SetupLinkOut:
    """One-time link for first sign-in (enroll) or credential reset. Shown once; deliver it out of band."""
    require_global_role(db, principal, ADMIN, "user.setup_link")
    user = _user_or_404(db, user_id)
    raw = accounts.issue_setup_token(db, principal.id, user, body.purpose, settings)
    notice = (
        "Deliver this link to the user through an approved channel. It is shown only once and works once."
    )
    if body.purpose == "reset":
        notice += " The user's previous password and authenticator were disabled and all sessions ended."
    return SetupLinkOut(
        setup_path=f"/setup#token={raw}", expires_in_seconds=settings.setup_token_seconds, notice=notice
    )


@router.post("/users/{user_id}/unlock", response_model=UserAdminOut)
def unlock_user(
    user_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> UserAdminOut:
    require_global_role(db, principal, ACCOUNT_SUPPORT, "user.unlock")
    user = _user_or_404(db, user_id)
    accounts.unlock(db, principal.id, user)
    return _user_out(db, user)


@router.post("/users/{user_id}/revoke-sessions", response_model=UserAdminOut)
def revoke_sessions(
    user_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> UserAdminOut:
    require_global_role(db, principal, ACCOUNT_SUPPORT, "user.revoke_sessions")
    user = _user_or_404(db, user_id)
    count = sess.revoke_all_for_user(db, user.id, "revoked_by_administrator")
    audit.record(
        db,
        actor_id=principal.id,
        action="user.revoke_sessions",
        entity_type="user",
        entity_id=user.id,
        details={"sessions_revoked": count},
    )
    db.commit()
    return _user_out(db, user)


# --- cohorts ------------------------------------------------------------------------------------
@router.get("/cohorts", response_model=list[CohortAdminOut])
def list_cohorts(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[CohortAdminOut]:
    require_global_role(db, principal, ADMIN, "admin.cohorts")
    return [_cohort_out(db, c) for c in db.scalars(select(Cohort).order_by(Cohort.start_date.desc()))]


@router.post("/cohorts", response_model=CohortDetailOut, status_code=201)
def create_cohort(
    body: CohortCreateIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CohortDetailOut:
    require_global_role(db, principal, ADMIN, "cohort.create")
    _check_timezone(body.timezone)
    if body.end_date < body.start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "End date must be on or after the start date"
        )
    if db.scalar(select(Cohort.id).where(Cohort.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cohort code already exists")
    cv = db.scalar(select(CourseVersion).order_by(CourseVersion.id.desc()).limit(1))
    if cv is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Import the curriculum before creating cohorts")
    cohort = Cohort(
        code=body.code,
        name=body.name.strip(),
        course_version_id=cv.id,
        start_date=body.start_date,
        end_date=body.end_date,
        timezone=body.timezone,
        status="active",
    )
    db.add(cohort)
    db.flush()
    audit.record(
        db,
        actor_id=principal.id,
        action="cohort.create",
        entity_type="cohort",
        entity_id=cohort.id,
        cohort_id=cohort.id,
        details={"code": cohort.code, "course_version": cv.version_label},
    )
    db.commit()
    return _cohort_detail(db, cohort)


@router.get("/cohorts/{cohort_id}", response_model=CohortDetailOut)
def cohort_detail(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CohortDetailOut:
    require_global_role(db, principal, ADMIN, "admin.cohort")
    return _cohort_detail(db, _cohort_or_404(db, cohort_id))


@router.patch("/cohorts/{cohort_id}", response_model=CohortDetailOut)
def update_cohort(
    cohort_id: int,
    body: CohortUpdateIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    require_global_role(db, principal, ADMIN, "cohort.update")
    cohort = _cohort_or_404(db, cohort_id)
    changes = body.model_dump(exclude_none=True)
    if "timezone" in changes:
        _check_timezone(changes["timezone"])
    start, end = changes.get("start_date", cohort.start_date), changes.get("end_date", cohort.end_date)
    if end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "End date must be on or after the start date"
        )
    changed = {k: str(v) for k, v in changes.items() if getattr(cohort, k) != v}
    for k in changed:
        setattr(cohort, k, changes[k])
    if changed:
        audit.record(
            db,
            actor_id=principal.id,
            action="cohort.update",
            entity_type="cohort",
            entity_id=cohort.id,
            cohort_id=cohort.id,
            details=changed,
        )
        db.commit()
    return _cohort_detail(db, cohort)


@router.post("/cohorts/{cohort_id}/members", response_model=CohortDetailOut)
def add_member(
    cohort_id: int,
    body: MemberIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    require_global_role(db, principal, ADMIN, "cohort.member.add")
    cohort = _cohort_or_404(db, cohort_id)
    user = _user_or_404(db, body.user_id)
    if not user.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot enroll an inactive user")
    if (body.role == "student") != (body.pathway is not None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Students require an assessed pathway; staff must not have one",
        )
    existing = list(
        db.scalars(
            select(CohortMembership).where(
                CohortMembership.cohort_id == cohort.id, CohortMembership.user_id == user.id
            )
        )
    )
    active_roles = {m.role for m in existing if m.status == "active"}
    if body.role in active_roles:
        raise HTTPException(status.HTTP_409_CONFLICT, f"User is already an active {body.role} in this cohort")
    is_student, has_staff = body.role == "student", bool(active_roles & {"instructor", "evaluator"})
    if (is_student and has_staff) or (not is_student and "student" in active_roles):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A user cannot be both a student and staff in the same cohort"
        )
    prior = next((m for m in existing if m.role == body.role), None)
    if prior is not None:  # re-activate a withdrawn membership instead of duplicating history
        if is_student and prior.pathway != body.pathway and _has_submissions(db, cohort.id, user.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This student has submitted work under another pathway; pathway cannot change",
            )
        prior.status, prior.pathway = "active", body.pathway
        membership_id = prior.id
    else:
        m = CohortMembership(
            cohort_id=cohort.id, user_id=user.id, role=body.role, pathway=body.pathway, status="active"
        )
        db.add(m)
        db.flush()
        membership_id = m.id
    audit.record(
        db,
        actor_id=principal.id,
        action="cohort.member.add",
        entity_type="cohort_membership",
        entity_id=membership_id,
        cohort_id=cohort.id,
        details={"user_id": user.id, "role": body.role, "pathway": body.pathway},
    )
    db.commit()
    return _cohort_detail(db, cohort)


@router.patch("/cohorts/{cohort_id}/members/{membership_id}", response_model=CohortDetailOut)
def update_member(
    cohort_id: int,
    membership_id: int,
    body: MemberUpdateIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    require_global_role(db, principal, ADMIN, "cohort.member.update")
    cohort = _cohort_or_404(db, cohort_id)
    m = db.get(CohortMembership, membership_id)
    if m is None or m.cohort_id != cohort.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    changes: dict[str, object] = {}
    if body.pathway is not None and body.pathway != m.pathway:
        if m.role != "student":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only students have a pathway")
        if _has_submissions(db, cohort.id, m.user_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This student has submitted work; the assessed pathway cannot change",
            )
        m.pathway = changes["pathway"] = body.pathway
    if body.status is not None and body.status != m.status:
        m.status = changes["status"] = body.status
        if body.status == "withdrawn" and m.role == "student":
            removed = db.execute(
                SquadMember.__table__.delete().where(
                    SquadMember.user_id == m.user_id,
                    SquadMember.squad_id.in_(select(Squad.id).where(Squad.cohort_id == cohort.id)),
                )
            ).rowcount
            changes["removed_from_squads"] = removed or 0
    if changes:
        audit.record(
            db,
            actor_id=principal.id,
            action="cohort.member.update",
            entity_type="cohort_membership",
            entity_id=m.id,
            cohort_id=cohort.id,
            details={"user_id": m.user_id, **changes},
        )
        db.commit()
    return _cohort_detail(db, cohort)


# --- squads (Program Administrator, or an instructor of the cohort) -----------------------------
def _squad_manager(db: Session, principal: Principal, cohort_id: int, action: str) -> Cohort:
    if "program_admin" not in principal.global_roles:
        require_cohort_role(db, principal, cohort_id, frozenset({"instructor"}), action)
    return _cohort_or_404(db, cohort_id)


@squad_router.post("", response_model=CohortDetailOut, status_code=201)
def create_squad(
    cohort_id: int,
    body: SquadIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    cohort = _squad_manager(db, principal, cohort_id, "squad.create")
    squad = Squad(cohort_id=cohort.id, name=body.name.strip())
    db.add(squad)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A squad with that name already exists") from exc
    audit.record(
        db,
        actor_id=principal.id,
        action="squad.create",
        entity_type="squad",
        entity_id=squad.id,
        cohort_id=cohort.id,
        details={"name": squad.name},
    )
    db.commit()
    return _cohort_detail(db, cohort)


@squad_router.put("/{squad_id}/members", response_model=CohortDetailOut)
def set_squad_members(
    cohort_id: int,
    squad_id: int,
    body: SquadMembersIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    """Replace a squad's membership. Members must be active students of the cohort; a student moving here
    is removed from any other squad in the cohort (one squad per student)."""
    cohort = _squad_manager(db, principal, cohort_id, "squad.members")
    squad = db.get(Squad, squad_id)
    if squad is None or squad.cohort_id != cohort.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Squad not found")
    wanted = set(body.user_ids)
    students = set(
        db.scalars(
            select(CohortMembership.user_id).where(
                CohortMembership.cohort_id == cohort.id,
                CohortMembership.role == "student",
                CohortMembership.status == "active",
                CohortMembership.user_id.in_(wanted or {0}),
            )
        )
    )
    if wanted - students:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Not active students of this cohort: {sorted(wanted - students)}",
        )
    cohort_squads = select(Squad.id).where(Squad.cohort_id == cohort.id)
    db.execute(SquadMember.__table__.delete().where(SquadMember.squad_id == squad.id))
    db.execute(
        SquadMember.__table__.delete().where(
            SquadMember.user_id.in_(wanted or {0}), SquadMember.squad_id.in_(cohort_squads)
        )
    )
    for uid in sorted(wanted):
        db.add(SquadMember(squad_id=squad.id, user_id=uid))
    audit.record(
        db,
        actor_id=principal.id,
        action="squad.members",
        entity_type="squad",
        entity_id=squad.id,
        cohort_id=cohort.id,
        details={"user_ids": sorted(wanted)},
    )
    db.commit()
    return _cohort_detail(db, cohort)


@squad_router.delete("/{squad_id}", response_model=CohortDetailOut)
def delete_squad(
    cohort_id: int,
    squad_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CohortDetailOut:
    cohort = _squad_manager(db, principal, cohort_id, "squad.delete")
    squad = db.get(Squad, squad_id)
    if squad is None or squad.cohort_id != cohort.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Squad not found")
    if db.scalar(select(Handoff.id).where(Handoff.squad_id == squad.id).limit(1)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This squad has recorded handoffs; keep it so contribution history is preserved",
        )
    name = squad.name
    db.execute(SquadMember.__table__.delete().where(SquadMember.squad_id == squad_id))
    db.execute(Squad.__table__.delete().where(Squad.id == squad_id))
    audit.record(
        db,
        actor_id=principal.id,
        action="squad.delete",
        entity_type="squad",
        entity_id=squad_id,
        cohort_id=cohort.id,
        details={"name": name},
    )
    db.commit()
    return _cohort_detail(db, cohort)


@squad_router.get("", response_model=CohortDetailOut)
def squads_for_instructor(
    cohort_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> CohortDetailOut:
    """Instructor view of cohort members and squads (needed to manage squads without admin rights)."""
    return _cohort_detail(db, _squad_manager(db, principal, cohort_id, "squad.view"))
