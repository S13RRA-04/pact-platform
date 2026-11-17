"""Schemas for sign-in, account setup and user/cohort administration."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"
COHORT_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{2,31}$"
GlobalRole = Literal["curriculum_editor", "content_approver", "program_admin", "secops_admin"]
CohortRole = Literal["student", "instructor", "evaluator"]
Pathway = Literal["investigator", "analyst"]


# --- sign-in ------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginOut(BaseModel):
    mfa_required: bool = True


class MfaIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SetupStartIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class SetupStartOut(BaseModel):
    username: str
    display_name: str
    purpose: str
    totp_secret: str
    otpauth_uri: str


class SetupCompleteIn(SetupStartIn):
    password: str = Field(min_length=1, max_length=256)
    totp_code: str = Field(min_length=6, max_length=8)


# --- users --------------------------------------------------------------------------------------
class UserCreateIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    global_roles: list[GlobalRole] = Field(default_factory=list)

    @field_validator("username", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: EmailStr | None = None
    active: bool | None = None


class RolesIn(BaseModel):
    roles: list[GlobalRole]


class SetupLinkIn(BaseModel):
    purpose: Literal["enroll", "reset"] = "enroll"


class SetupLinkOut(BaseModel):
    setup_path: str
    expires_in_seconds: int
    notice: str


class CohortRoleOut(BaseModel):
    membership_id: int
    cohort_id: int
    cohort_code: str
    role: str
    pathway: str | None
    status: str


class UserAdminOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str
    active: bool
    is_synthetic: bool
    is_dev_persona: bool
    global_roles: list[str]
    cohort_roles: list[CohortRoleOut]
    credential_state: str
    last_login_at: datetime | None
    locked_until: datetime | None
    has_active_session: bool
    setup_link_expires_at: datetime | None


# --- cohorts ------------------------------------------------------------------------------------
class CohortCreateIn(BaseModel):
    code: str = Field(pattern=COHORT_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    start_date: Date
    end_date: Date
    timezone: str = Field(default="America/Chicago", max_length=64)

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v


class CohortUpdateIn(BaseModel):
    code: str | None = Field(default=None, pattern=COHORT_CODE_PATTERN)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: Date | None = None
    end_date: Date | None = None
    timezone: str | None = Field(default=None, max_length=64)
    status: Literal["active", "archived"] | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper() if isinstance(v, str) else v


class MemberIn(BaseModel):
    user_id: int
    role: CohortRole
    pathway: Pathway | None = None


class MemberUpdateIn(BaseModel):
    pathway: Pathway | None = None
    status: Literal["active", "withdrawn"] | None = None


class MemberOut(BaseModel):
    membership_id: int
    user_id: int
    username: str
    display_name: str
    role: str
    pathway: str | None
    status: str
    squad_id: int | None
    squad_name: str | None
    has_submissions: bool


class SquadAdminOut(BaseModel):
    id: int
    name: str
    member_ids: list[int]


class CohortAdminOut(BaseModel):
    id: int
    code: str
    name: str
    start_date: Date
    end_date: Date
    timezone: str
    status: str
    course_version: str
    counts: dict[str, int]


class CohortDetailOut(CohortAdminOut):
    members: list[MemberOut]
    squads: list[SquadAdminOut]


class SquadIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SquadMembersIn(BaseModel):
    user_ids: list[int] = Field(max_length=40)
