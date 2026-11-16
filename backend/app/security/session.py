"""Signed, HttpOnly session cookie. Stateless; contains only the user id and issue time."""

from __future__ import annotations

from fastapi import Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Settings

COOKIE_NAME = "pact_session"
CSRF_HEADER = "X-PACT-Request"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="pact-session-v1")


def issue(response: Response, settings: Settings, user_id: int, provider: str) -> None:
    token = _serializer(settings).dumps({"uid": user_id, "idp": provider})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read(token: str | None, settings: Settings) -> int | None:
    if not token:
        return None
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_max_age_seconds)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
