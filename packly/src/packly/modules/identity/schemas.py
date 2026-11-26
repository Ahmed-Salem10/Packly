import uuid
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from packly.modules.identity.models import MembershipType, OrgType
from packly.modules.identity.utils.phone import normalize_phone

Name150 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
Name100 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Address200 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class _PhoneMixin(BaseModel):
    """Normalizes any Egyptian mobile format to +20XXXXXXXXXX.

    InvalidPhoneError subclasses ValueError, so pydantic reports it as a
    normal validation error.
    """

    phone: str

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_phone(v)


# ───────────────────────── Users ─────────────────────────
class UserCreate(_PhoneMixin):
    name: Name150
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) > 100:
            raise ValueError("Email must be at most 100 characters.")
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    name: str
    email: str


# ───────────────────────── Organizations ─────────────────────────
class OrganizationCreate(BaseModel):
    name: Name100
    org_type: OrgType
    address: Address200


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: OrgType
    verified: bool
    address: str


# ───────────────────────── Memberships ─────────────────────────
class MemberAdd(_PhoneMixin):
    role: MembershipType = MembershipType.member


class MemberRoleUpdate(BaseModel):
    role: MembershipType


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: MembershipType


class UserOrganizationRead(BaseModel):
    """An organization together with the current user's role in it."""

    organization: OrganizationRead
    role: MembershipType


# ───────────────────────── OTP ─────────────────────────
class OTPRequest(_PhoneMixin):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=10, max_length=32, description="User phone number")


class OTPVerify(_PhoneMixin):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=10, max_length=32)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    organization_id: uuid.UUID | None = None


class OTPRequestResponse(BaseModel):
    message: str


class OTPVerifyResponse(BaseModel):
    message: str
    verified: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=20, max_length=200)


class LogoutRequest(RefreshRequest):
    pass


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str
    organization_id: uuid.UUID | None
    role: str | None
