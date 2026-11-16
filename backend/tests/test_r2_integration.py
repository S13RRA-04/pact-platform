"""Opt-in destructive test scoped to a unique prefix in an isolated staging bucket."""

import os
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.services.object_storage import ObjectStorage

required = (
    "PACT_R2_TEST_ENDPOINT_URL",
    "PACT_R2_TEST_BUCKET",
    "PACT_R2_TEST_ACCESS_KEY_ID",
    "PACT_R2_TEST_SECRET_ACCESS_KEY",
)
pytestmark = pytest.mark.r2_integration


@pytest.mark.skipif(
    not all(os.getenv(k) for k in required), reason="isolated R2 staging credentials not configured"
)
def test_private_r2_round_trip(tmp_path: Path):
    settings = Settings(
        env="test",
        object_storage_provider="r2",
        r2_endpoint_url=os.environ[required[0]],
        r2_bucket=os.environ[required[1]],
        r2_access_key_id=os.environ[required[2]],
        r2_secret_access_key=os.environ[required[3]],
    )
    storage = ObjectStorage(settings)
    key = f"integration-tests/{uuid.uuid4().hex}/probe.txt"
    source = tmp_path / "probe.txt"
    source.write_bytes(b"PACT R2 integration probe")
    try:
        storage.put_file(key, source)
        assert storage.open(key).read() == b"PACT R2 integration probe"
    finally:
        storage.delete(key)
