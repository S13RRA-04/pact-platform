"""Local account lifecycle: sign-in with mandatory TOTP, one-time setup links, password change.

Security properties:
- One generic failure message for unknown user, wrong password, locked, inactive or not-set-up accounts.
- Failed password *and* failed TOTP attempts count toward the same lockout.
- Each TOTP code is accepted at most once (stored counter).
- A fresh session token is issued after MFA (no reuse of the pre-MFA token).
- Every outcome is audited.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.models import AccountSetupToken, AuthSession, User, UserCredential
from app.security import passwords, totp
from app.security import session as sess

PROVIDER = "local"
GENERIC_FAILURE = "Sign-in failed. Check your credentials, or contact your program administrator."
SETUP_FAILURE = "This setup link is invalid, expired or already used. Ask your administrator for a new one."


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fail(db: Session, *, user_id: int | None, reason: str, username: str) -> HTTPException:
    audit.record(
        db,
        actor_id=user_id,
        action="auth.login",
        outcome="denied",
        entity_type="user",
        entity_id=user_id,
        details={"reason": reason, "username": username[:64]},
    )
    db.commit()
    return HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_FAILURE)


def _register_failure(cred: UserCredential, settings: Settings) -> bool:
    """Count a failed factor; returns True when this failure locks the account."""
    cred.failed_attempts += 1
    if cred.failed_attempts >= settings.login_max_failures:
        cred.locked_until = _now() + timedelta(seconds=settings.login_lockout_seconds)
        cred.failed_attempts = 0
        return True
    return False


def _locked(cred: UserCredential) -> bool:
    return cred.locked_until is not None and cred.locked_until > _now()


# --- sign-in ---------------------------------------------------------------------------------------
def begin_login(
    db: Session, request: Request, response: Response, settings: Settings, username: str, password: str
) -> None:
    """Verify the password and open a short-lived session that is only good for the MFA step."""
    username = username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    cred = db.get(UserCredential, user.id) if user else None
    usable = (
        user is not None
        and user.active
        and not user.is_dev_persona
        and cred is not None
        and cred.password_hash is not None
        and cred.totp_secret_encrypted is not None
    )
    # Always run one Argon2 verification so response time does not reveal which check failed.
    password_ok = passwords.verify_password(cred.password_hash if usable and cred else None, password)
    if not usable or cred is None or user is None:
        raise _fail(db, user_id=user.id if user else None, reason="unknown_or_unavailable", username=username)
    if _locked(cred):
        raise _fail(db, user_id=user.id, reason="locked", username=username)
    if not password_ok:
        locked = _register_failure(cred, settings)
        raise _fail(
            db, user_id=user.id, reason="bad_password" + ("+locked" if locked else ""), username=username
        )
    if passwords.needs_rehash(cred.password_hash or ""):
        cred.password_hash = passwords.hash_password(password)
    sess.create(
        db, response, settings, user_id=user.id, provider=PROVIDER, mfa_verified=False, request=request
    )
    audit.record(db, actor_id=user.id, action="auth.password_verified", entity_type="user", entity_id=user.id)
    db.commit()


def complete_mfa(db: Session, request: Request, response: Response, settings: Settings, code: str) -> User:
    pending = sess.lookup(db, request, settings)
    if pending is None or pending.mfa_verified or pending.provider != PROVIDER:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in session expired. Start again.")
    user = db.get(User, pending.user_id)
    cred = db.get(UserCredential, pending.user_id, with_for_update=True)
    if user is None or not user.active or cred is None or cred.totp_secret_encrypted is None:
        sess.revoke(pending, "unavailable")
        raise _fail(db, user_id=pending.user_id, reason="unavailable_at_mfa", username="")
    if _locked(cred):
        sess.revoke(pending, "locked")
        raise _fail(db, user_id=user.id, reason="locked", username=user.username)
    secret = totp.decrypt(cred.totp_secret_encrypted, settings)
    counter = totp.matching_counter(secret, code) if secret else None
    if counter is None or (cred.last_totp_counter is not None and counter <= cred.last_totp_counter):
        locked = _register_failure(cred, settings)
        if locked:
            sess.revoke(pending, "locked")
        reason = "bad_totp" if counter is None else "totp_replay"
        raise _fail(
            db, user_id=user.id, reason=reason + ("+locked" if locked else ""), username=user.username
        )
    cred.last_totp_counter = counter
    cred.failed_attempts = 0
    cred.locked_until = None
    cred.last_login_at = _now()
    sess.revoke(pending, "mfa_completed")
    sess.create(
        db, response, settings, user_id=user.id, provider=PROVIDER, mfa_verified=True, request=request
    )
    audit.record(
        db,
        actor_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        details={"provider": PROVIDER, "mfa": "totp"},
    )
    db.commit()
    return user


def logout(db: Session, request: Request, response: Response, settings: Settings) -> None:
    record = sess.lookup(db, request, settings)
    if record is not None:
        sess.revoke(record, "logout")
        audit.record(
            db, actor_id=record.user_id, action="auth.logout", entity_type="user", entity_id=record.user_id
        )
        db.commit()
    sess.clear(response)


def change_password(
    db: Session, user: User, session_id: int | None, settings: Settings, current: str, new: str
) -> None:
    cred = db.get(UserCredential, user.id, with_for_update=True)
    if cred is None or not passwords.verify_password(cred.password_hash, current):
        if cred is not None:
            _register_failure(cred, settings)
        audit.record(
            db,
            actor_id=user.id,
            action="auth.password_change",
            outcome="denied",
            entity_type="user",
            entity_id=user.id,
            details={"reason": "bad_current_password"},
        )
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    problems = passwords.policy_violations(new, user.username, settings)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, " ".join(problems))
    cred.password_hash = passwords.hash_password(new)
    cred.password_set_at = _now()
    revoked = sess.revoke_all_for_user(db, user.id, "password_changed", except_id=session_id)
    audit.record(
        db,
        actor_id=user.id,
        action="auth.password_change",
        entity_type="user",
        entity_id=user.id,
        details={"other_sessions_revoked": revoked},
    )
    db.commit()


# --- one-time setup links --------------------------------------------------------------------------
def issue_setup_token(db: Session, actor_id: int, user: User, purpose: str, settings: Settings) -> str:
    if user.is_dev_persona:
        raise HTTPException(status.HTTP_409_CONFLICT, "Development personas cannot hold local credentials")
    if not user.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reactivate the account before issuing a setup link")
    # Only the newest link works.
    db.execute(
        update(AccountSetupToken)
        .where(AccountSetupToken.user_id == user.id, AccountSetupToken.used_at.is_(None))
        .values(used_at=_now())
    )
    revoked = 0
    if purpose == "reset":
        # A reset is issued because a factor may be lost or compromised: disable both factors immediately.
        cred = db.get(UserCredential, user.id)
        if cred is not None:
            cred.password_hash = None
            cred.totp_secret_encrypted = None
            cred.totp_enabled_at = None
            cred.last_totp_counter = None
        revoked = sess.revoke_all_for_user(db, user.id, "credential_reset")
    raw = secrets.token_urlsafe(32)
    db.add(
        AccountSetupToken(
            token_hash=_hash(raw),
            user_id=user.id,
            purpose=purpose,
            created_by_id=actor_id,
            expires_at=_now() + timedelta(seconds=settings.setup_token_seconds),
        )
    )
    audit.record(
        db,
        actor_id=actor_id,
        action=f"account.setup_link.{purpose}",
        entity_type="user",
        entity_id=user.id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    return raw


def _live_token(db: Session, raw: str) -> tuple[AccountSetupToken, User]:
    token = db.scalar(
        select(AccountSetupToken).where(AccountSetupToken.token_hash == _hash(raw)).with_for_update()
    )
    user = db.get(User, token.user_id) if token else None
    if (
        token is None
        or user is None
        or token.used_at is not None
        or token.expires_at <= _now()
        or not user.active
    ):
        raise HTTPException(status.HTTP_410_GONE, SETUP_FAILURE)
    return token, user


def start_setup(db: Session, raw: str, settings: Settings) -> dict[str, str]:
    token, user = _live_token(db, raw)
    secret = totp.new_secret()
    token.pending_totp_secret_encrypted = totp.encrypt(secret, settings)
    db.commit()
    return {
        "username": user.username,
        "display_name": user.display_name,
        "purpose": token.purpose,
        "totp_secret": secret,
        "otpauth_uri": totp.provisioning_uri(secret, user.username),
    }


def complete_setup(db: Session, raw: str, password: str, code: str, settings: Settings) -> None:
    token, user = _live_token(db, raw)
    if token.pending_totp_secret_encrypted is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Open the setup link again to generate an authenticator key"
        )
    problems = passwords.policy_violations(password, user.username, settings)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, " ".join(problems))
    secret = totp.decrypt(token.pending_totp_secret_encrypted, settings)
    counter = totp.matching_counter(secret, code) if secret else None
    if counter is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That authenticator code is not valid. Check your device clock and try again.",
        )
    cred = db.get(UserCredential, user.id)
    if cred is None:
        cred = UserCredential(user_id=user.id, failed_attempts=0)
        db.add(cred)
    now = _now()
    cred.password_hash = passwords.hash_password(password)
    cred.password_set_at = now
    cred.totp_secret_encrypted = token.pending_totp_secret_encrypted
    cred.totp_enabled_at = now
    cred.last_totp_counter = counter  # the enrollment code cannot be replayed at sign-in
    cred.failed_attempts = 0
    cred.locked_until = None
    token.used_at = now
    sess.revoke_all_for_user(db, user.id, "credential_setup")
    audit.record(
        db,
        actor_id=user.id,
        action=f"account.setup_completed.{token.purpose}",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()


# --- administrator support --------------------------------------------------------------------------
def account_state(db: Session, user: User) -> dict[str, object]:
    cred = db.get(UserCredential, user.id)
    now = _now()
    active_sessions = db.scalar(
        select(AuthSession.id)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.mfa_verified.is_(True),
            AuthSession.expires_at > now,
        )
        .limit(1)
    )
    pending_link = db.scalar(
        select(AccountSetupToken.expires_at)
        .where(
            AccountSetupToken.user_id == user.id,
            AccountSetupToken.used_at.is_(None),
            AccountSetupToken.expires_at > now,
        )
        .limit(1)
    )
    if user.is_dev_persona:
        state = "dev_persona"
    elif cred is None or cred.password_hash is None or cred.totp_secret_encrypted is None:
        state = "setup_pending" if pending_link else "not_set_up"
    elif _locked(cred):
        state = "locked"
    else:
        state = "active"
    return {
        "credential_state": state,
        "last_login_at": cred.last_login_at if cred else None,
        "locked_until": cred.locked_until if cred and _locked(cred) else None,
        "has_active_session": active_sessions is not None,
        "setup_link_expires_at": pending_link,
    }


def unlock(db: Session, actor_id: int, user: User) -> None:
    cred = db.get(UserCredential, user.id)
    if cred is not None:
        cred.locked_until = None
        cred.failed_attempts = 0
    audit.record(db, actor_id=actor_id, action="account.unlock", entity_type="user", entity_id=user.id)
    db.commit()
