from __future__ import annotations

import os
from pathlib import Path

os.environ["PACT_ENV"] = "test"
os.environ["PACT_DEV_PERSONAS"] = "true"
os.environ["PACT_SESSION_SECRET"] = "test-only-session-secret-at-least-32-characters"

import pytest
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from alembic import command as alembic_command
from app.config import Settings, get_settings
from app.curriculum_import.presentations import import_presentations
from app.db import get_engine
from app.main import create_app
from app.seed.seed import reset, seed

BACKEND_DIR = Path(__file__).resolve().parents[1]


def build_schema_from_migrations(engine: Engine, url: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    config = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["url"] = url
    alembic_command.upgrade(config, "head")


@pytest.fixture(scope="session")
def client() -> TestClient:
    settings = Settings()
    engine = get_engine(settings.test_database_url)
    # The test database is disposable. Rebuild it through the real migrations (not create_all) so tests
    # exercise the production schema, including the append-only triggers installed by migration 0001.
    build_schema_from_migrations(engine, settings.test_database_url)
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        reset(db)
        seed(db, settings, settings.curriculum_source, Path("../docs/reports/test-import.md"))
        import_presentations(db, Path("../pact curriculum/PACT_Redesigned_Presentation_Suite_v0.2"))
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    from app.db import get_db

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client: TestClient):
    def do(username: str) -> None:
        response = client.post("/api/dev/login", json={"username": username}, headers={"X-PACT-Request": "1"})
        assert response.status_code == 200, response.text

    return do


@pytest.fixture
def mutate_headers() -> dict[str, str]:
    return {"X-PACT-Request": "1"}
