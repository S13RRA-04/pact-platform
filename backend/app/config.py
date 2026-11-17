"""Environment-based configuration.

All settings come from environment variables (prefix ``PACT_``) or the repository ``.env`` file.
Production-like environments fail closed: the development persona switcher is disabled and a
session secret is mandatory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PACT_",
        env_file=(str(REPO_ROOT / ".env"),),
        extra="ignore",
    )

    env: Environment = "production"
    dev_personas: bool = False
    database_url: str = "postgresql+psycopg://pact:pact_dev_only@127.0.0.1:55432/pact"
    test_database_url: str = "postgresql+psycopg://pact:pact_dev_only@127.0.0.1:55432/pact_test"
    session_secret: str = ""
    session_max_age_seconds: int = 8 * 60 * 60
    cookie_secure: bool = False
    curriculum_source: Path = (
        REPO_ROOT / "source-data" / "curriculum" / "PACT_Task_Objective_Assessment_Matrix_v0.1.xlsx"
    )
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30
    object_storage_provider: Literal["filesystem", "r2"] = "filesystem"
    object_storage_directory: Path = REPO_ROOT / ".data" / "protected-documents"
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    download_token_seconds: int = 300
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 30
    # Local account authentication
    totp_encryption_key: str = ""  # Fernet key; required in production
    session_idle_timeout_seconds: int = 30 * 60
    mfa_pending_seconds: int = 5 * 60
    login_max_failures: int = 5
    login_lockout_seconds: int = 15 * 60
    setup_token_seconds: int = 72 * 60 * 60
    password_min_length: int = 12

    @model_validator(mode="after")
    def _fail_closed(self) -> Settings:
        if self.env == "production":
            if len(self.session_secret) < 32:
                raise ValueError("PACT_SESSION_SECRET (>=32 chars) is required outside development/test")
            # Never allow the persona switcher outside development, regardless of the flag.
            self.dev_personas = False
            if self.object_storage_provider != "r2" or not all(
                (self.r2_endpoint_url, self.r2_bucket, self.r2_access_key_id, self.r2_secret_access_key)
            ):
                raise ValueError("Production requires private R2 object storage configuration")
            if not self.clamav_host:
                raise ValueError("Production requires PACT_CLAMAV_HOST")
            if not self.totp_encryption_key:
                raise ValueError("Production requires PACT_TOTP_ENCRYPTION_KEY (Fernet key)")
            if not self.cookie_secure:
                raise ValueError("Production requires PACT_COOKIE_SECURE=true (HTTPS-only session cookie)")
        if not self.session_secret:
            # Development/test only: ephemeral per-process secret. Sessions reset on restart.
            import secrets

            self.session_secret = secrets.token_urlsafe(48)
        return self

    @property
    def dev_personas_enabled(self) -> bool:
        """Persona switcher is only ever active in development (or the automated test env)."""
        return self.dev_personas and self.env in ("development", "test")

    @property
    def synthetic_only(self) -> bool:
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
