from __future__ import annotations

import os
from pathlib import Path

os.environ["PACT_ENV"] = "test"
os.environ["PACT_DEV_PERSONAS"] = "true"
os.environ["PACT_SESSION_SECRET"] = "test-only-session-secret-at-least-32-characters"

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.curriculum_import.presentations import import_presentations
from app.db import get_engine
from app.main import create_app
from app.models import Base
from app.seed.seed import reset, seed


@pytest.fixture(scope="session")
def client() -> TestClient:
    settings = Settings()
    engine = get_engine(settings.test_database_url)
    # The test database is disposable; rebuild it so model changes cannot leave a stale schema.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
