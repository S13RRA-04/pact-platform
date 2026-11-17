from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Cohort, User
from app.schemas.accounts import (
    LoginIn,
    LoginOut,
    MfaIn,
    PasswordChangeIn,
    SetupCompleteIn,
    SetupStartIn,
    SetupStartOut,
)
from app.schemas.common import DevLoginIn, MembershipOut, MeOut, PersonaOut
from app.security import session as sess
from app.security.authz import Principal, get_principal, require_csrf_header
from app.security.identity import DevPersonaProvider
from app.services import accounts

router = APIRouter(prefix="/api", tags=["auth"])
dev_router = APIRouter(prefix="/api/dev", tags=["development-only"])


def _require_dev(settings: Settings = Depends(get_settings)) -> Settings:
    # Defense in depth: the router is only mounted in development, and each handler re-checks.
    if not settings.dev_personas_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return settings


@dev_router.get("/personas", response_model=list[PersonaOut])
def list_personas(db: Session = Depends(get_db), _: Settings = Depends(_require_dev)) -> list[User]:
    return list(
        db.scalars(select(User).where(User.is_dev_persona.is_(True), User.active.is_(True)).order_by(User.id))
    )


@dev_router.post("/login", response_model=PersonaOut)
def dev_login(
    body: DevLoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(_require_dev),
) -> User:
    provider = DevPersonaProvider(settings)
    user = provider.authenticate(db, body.username)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown persona")
    # Personas have no second factor; the session is marked verified only because this path exists
    # exclusively in development and test.
    sess.create(
        db, response, settings, user_id=user.id, provider=provider.name, mfa_verified=True, request=request
    )
    audit.record(
        db,
        actor_id=user.id,
        action="auth.dev_login",
        entity_type="user",
        entity_id=user.id,
        details={"provider": provider.name},
    )
    db.commit()
    return user


@router.post("/auth/login", response_model=LoginOut, dependencies=[Depends(require_csrf_header)])
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginOut:
    """Step 1: password. Opens a short-lived session usable only for the authenticator-code step."""
    accounts.begin_login(db, request, response, settings, body.username, body.password)
    return LoginOut(mfa_required=True)


@router.post("/auth/mfa", status_code=204, dependencies=[Depends(require_csrf_header)])
def verify_mfa(
    body: MfaIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Step 2: authenticator code. Replaces the pending session with a fully authenticated one."""
    accounts.complete_mfa(db, request, response, settings, body.code)
    response.status_code = 204
    return response


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    accounts.logout(db, request, response, settings)
    response.status_code = 204
    return response


@router.post("/auth/password", status_code=204, dependencies=[Depends(require_csrf_header)])
def change_password(
    body: PasswordChangeIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    if principal.user.is_dev_persona:
        raise HTTPException(status.HTTP_409_CONFLICT, "Development personas have no password")
    accounts.change_password(
        db, principal.user, principal.session_id, settings, body.current_password, body.new_password
    )


@router.post("/auth/setup/start", response_model=SetupStartOut, dependencies=[Depends(require_csrf_header)])
def setup_start(
    body: SetupStartIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SetupStartOut:
    """Open a one-time setup link: returns a new authenticator key to enroll (not yet active)."""
    return SetupStartOut(**accounts.start_setup(db, body.token, settings))


@router.post("/auth/setup/complete", status_code=204, dependencies=[Depends(require_csrf_header)])
def setup_complete(
    body: SetupCompleteIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> None:
    """Set the password and activate the authenticator after proving possession with a valid code."""
    accounts.complete_setup(db, body.token, body.password, body.totp_code, settings)


@router.get("/me", response_model=MeOut)
def me(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    cohorts = {
        c.id: c
        for c in db.scalars(
            select(Cohort).where(Cohort.id.in_([m.cohort_id for m in principal.memberships] or [0]))
        )
    }
    return MeOut(
        id=principal.id,
        username=principal.user.username,
        display_name=principal.user.display_name,
        persona_label=principal.user.persona_label,
        global_roles=sorted(principal.global_roles),
        memberships=[
            MembershipOut(
                cohort_id=m.cohort_id,
                cohort_code=cohorts[m.cohort_id].code,
                cohort_name=cohorts[m.cohort_id].name,
                role=m.role,
                pathway=m.pathway,
            )
            for m in sorted(principal.memberships, key=lambda m: (m.cohort_id, m.role))
        ],
        environment=settings.env,
        synthetic_only=settings.synthetic_only,
        identity_provider="dev-persona" if principal.user.is_dev_persona else accounts.PROVIDER,
    )
