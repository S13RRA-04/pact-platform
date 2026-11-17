"""Server-side sessions. The cookie holds a random token; the database stores only its SHA-256.

Sessions can be revoked individually or per user (logout, deactivation, password reset, administrator
action), expire after an absolute lifetime, and end after an idle period.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthSession

COOKIE_NAME = "pact_session"
CSRF_HEADER = "X-PACT-Request"
LAST_SEEN_RESOLUTION = timedelta(seconds=60)  # avoid a write on every request


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def create(
    db: Session,
    response: Response,
    settings: Settings,
    *,
    user_id: int,
    provider: str,
    mfa_verified: bool,
    request: Request | None = None,
) -> AuthSession:
    token = secrets.token_urlsafe(32)
    lifetime = settings.session_max_age_seconds if mfa_verified else settings.mfa_pending_seconds
    now = _now()
    record = AuthSession(
        token_hash=_hash(token),
        user_id=user_id,
        provider=provider,
        mfa_verified=mfa_verified,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=lifetime),
        client_ip=(request.client.host if request and request.client else None),
        user_agent=(request.headers.get("user-agent", "")[:256] if request else None),
    )
    db.add(record)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=lifetime,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return record


def clear(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def lookup(db: Session, request: Request, settings: Settings) -> AuthSession | None:
    """Return the live session for the request cookie, enforcing expiry and idle timeout."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    record = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if record is None or record.revoked_at is not None:
        return None
    now = _now()
    idle_limit = record.last_seen_at + timedelta(seconds=settings.session_idle_timeout_seconds)
    if record.expires_at <= now or idle_limit <= now:
        record.revoked_at, record.revoked_reason = now, "expired"
        db.commit()
        return None
    if now - record.last_seen_at >= LAST_SEEN_RESOLUTION:
        record.last_seen_at = now
        db.commit()
    return record


def revoke(record: AuthSession, reason: str) -> None:
    if record.revoked_at is None:
        record.revoked_at, record.revoked_reason = _now(), reason


def revoke_all_for_user(db: Session, user_id: int, reason: str, *, except_id: int | None = None) -> int:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    if except_id is not None:
        stmt = stmt.where(AuthSession.id != except_id)
    return db.execute(stmt).rowcount or 0
