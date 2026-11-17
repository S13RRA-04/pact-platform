"""Argon2id password hashing and a NIST SP 800-63B-style password policy (length over composition)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import Settings

MAX_LENGTH = 128
_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id, RFC 9106 low-memory profile
# Precomputed so unknown-user logins spend the same time as a real verification.
_DUMMY_HASH = _hasher.hash("pact-timing-equalizer-not-a-password")

# Small local denylist. A production deployment should also screen against a breached-password corpus.
COMMON = {
    "password1234",
    "passwordpassword",
    "123456789012",
    "qwertyuiopas",
    "letmeinletmein",
    "welcome12345",
    "changeme1234",
    "administrator",
    "pactpassword",
    "trainingpassword",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    """Constant-work verification; a missing hash still performs a full Argon2 verification."""
    try:
        return _hasher.verify(encoded or _DUMMY_HASH, password) and encoded is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded: str) -> bool:
    return _hasher.check_needs_rehash(encoded)


def policy_violations(password: str, username: str, settings: Settings) -> list[str]:
    problems = []
    if len(password) < settings.password_min_length:
        problems.append(f"Use at least {settings.password_min_length} characters.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if username and username.lower() in lowered:
        problems.append("Do not include your username.")
    if lowered in COMMON or len(set(password)) < 4:
        problems.append("Choose a less predictable password.")
    return problems
