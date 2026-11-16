"""Identity provider boundary.

The application depends only on ``IdentityProvider``. The development persona provider is the only
implementation in this prototype; an approved agency IdP (OIDC/SAML/PIV) would be a new implementation
that resolves an authenticated external subject to a local ``User``.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User


class IdentityProvider(Protocol):
    name: str

    def authenticate(self, db: Session, credential: str) -> User | None: ...


class DevPersonaProvider:
    """Development-only. Authenticates by persona username, without a password.

    Refuses to operate unless the settings explicitly enable personas in a development/test environment.
    """

    name = "dev-persona"

    def __init__(self, settings: Settings) -> None:
        if not settings.dev_personas_enabled:
            raise RuntimeError("Development persona provider is disabled in this environment")

    def authenticate(self, db: Session, credential: str) -> User | None:
        return db.scalar(
            select(User).where(
                User.username == credential, User.is_dev_persona.is_(True), User.active.is_(True)
            )
        )
