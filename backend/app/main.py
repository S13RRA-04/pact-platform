"""PACT API application factory."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    admin,
    admin_users,
    assignments,
    auth,
    cases,
    curriculum,
    materials,
    release,
    staff,
    student,
)
from app.config import Settings, get_settings
from app.db import get_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="PACT Learning & Case Simulation Platform API",
        version="0.1.0",
        description="Synthetic-data development prototype. Not authorized for operational use.",
        docs_url="/api/docs" if settings.env != "production" else None,
        openapi_url="/api/openapi.json" if settings.env != "production" else None,
    )

    @app.get("/api/health", tags=["health"])
    def health(db: Session = Depends(get_db)) -> dict[str, object]:
        db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "environment": settings.env,
            "synthetic_only": True,
            "dev_personas_enabled": settings.dev_personas_enabled,
            "database": "ok",
        }

    @app.middleware("http")
    async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-PACT-Data-Classification", "SYNTHETIC-TRAINING-DATA")
        return response

    app.include_router(auth.router)
    if settings.dev_personas_enabled:
        app.include_router(auth.dev_router)
    for r in (
        curriculum.router,
        cases.router,
        assignments.router,
        student.router,
        staff.router,
        admin.router,
        admin_users.router,
        admin_users.squad_router,
        release.router,
        materials.router,
    ):
        app.include_router(r)
    return app


app = create_app()
