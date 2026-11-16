from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Cohort, User
from app.schemas.common import DevLoginIn, MembershipOut, MeOut, PersonaOut
from app.security import session as sess
from app.security.authz import Principal, get_principal
from app.security.identity import DevPersonaProvider

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
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(_require_dev),
) -> User:
    provider = DevPersonaProvider(settings)
    user = provider.authenticate(db, body.username)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown persona")
    sess.issue(response, settings, user.id, provider.name)
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


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> Response:
    sess.clear(response)
    response.status_code = 204
    return response


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
        identity_provider="dev-persona" if principal.user.is_dev_persona else "external",
    )
