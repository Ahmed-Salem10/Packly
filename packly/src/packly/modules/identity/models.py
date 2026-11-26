import enum
import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packly.core.models import Base, IdMixin, TimestampMixin


class Users(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    phone: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class OrgType(str, enum.Enum):
    buyer = "buyer"
    factory = "factory"
    staff = "staff"


class MembershipType(str, enum.Enum):
    owner = "owner"
    member = "member"
    viewer = "viewer"


class Organizations(Base, IdMixin, TimestampMixin):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[OrgType] = mapped_column(
        Enum(OrgType, native_enum=False, length=20), nullable=False
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)


class Memberships(Base, IdMixin, TimestampMixin):
    __tablename__ = "memberships"

    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[MembershipType] = mapped_column(
        Enum(MembershipType, native_enum=False, length=20),
        nullable=False,
    )


class Sessions(Base, IdMixin, TimestampMixin):
    """One row per refresh token (a login on one device). Only the hash is stored."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    expires_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
