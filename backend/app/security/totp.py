"""RFC 6238 authenticator codes with encrypted seeds and single-use enforcement."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

ISSUER = "PACT Training"
VALID_WINDOW = 1  # accept the previous/next 30-second step to tolerate clock skew


def _fernet(settings: Settings) -> Fernet:
    key = settings.totp_encryption_key
    if not key:
        if settings.env == "production":
            raise RuntimeError("PACT_TOTP_ENCRYPTION_KEY is required in production")
        # Development/test only: derive a stable key from the session secret.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.session_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt(secret: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt(token: str, settings: Settings) -> str | None:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def matching_counter(secret: str, code: str, now: datetime | None = None) -> int | None:
    """Return the time-step counter the code matches (within the window), or None."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = totp.timecode(now or datetime.now(UTC))
    for counter in range(current - VALID_WINDOW, current + VALID_WINDOW + 1):
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None
