import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packly.core.config import get_settings
from packly.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from packly.modules.identity.models import (
    Memberships,
    MembershipType,
    Organizations,
    OrgType,
    Users,
)
from packly.modules.identity.repository import (
    MembershipRepository,
    OrganizationRepository,
    SessionRepository,
    UserRepository,
)
from packly.modules.identity.schemas import (
    MemberAdd,
    MemberRoleUpdate,
    OrganizationCreate,
    UserCreate,
)
from packly.modules.identity.utils.phone import normalize_phone


# ───────────────────────── Exceptions ─────────────────────────
class IdentityError(Exception):
    """Base class for all identity-module errors."""


class UserAlreadyExistsError(IdentityError):
    pass


class OrganizationAlreadyExistsError(IdentityError):
    pass


class UserNotFoundError(IdentityError):
    pass


class OrganizationNotFoundError(IdentityError):
    pass


class MembershipNotFoundError(IdentityError):
    pass


class MembershipAlreadyExistsError(IdentityError):
    pass


class PermissionDeniedError(IdentityError):
    pass


class LastOwnerError(IdentityError):
    """Raised when an action would leave an organization without an owner."""


class InvalidRefreshTokenError(IdentityError):
    pass


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


# ───────────────────────── Service ─────────────────────────
class IdentityService:
    """Business rules for users, organizations, memberships and sessions.

    The service owns commits and rollbacks. Repositories only flush.
    Every write operation rolls back the current transaction if it fails.
    """

    SELF_SERVICE_ORG_TYPES: ClassVar[set[OrgType]] = {
        OrgType.buyer,
        OrgType.factory,
    }

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)
        self.sessions = SessionRepository(session)

    # ───────── Users ─────────
    async def register_user(self, data: UserCreate) -> Users:
        try:
            phone = normalize_phone(data.phone)

            if await self.users.get_user_by_phone(phone):
                raise UserAlreadyExistsError("Phone number already registered.")

            if data.email and await self.users.get_user_by_email(data.email):
                raise UserAlreadyExistsError("Email already registered.")

            user = await self.users.create_user(
                phone=phone,
                name=data.name,
                email=data.email,
            )
            await self.session.commit()
            return user

        except IntegrityError:
            await self.session.rollback()
            # Do not translate every IntegrityError into "duplicate user":
            # it may be a different database constraint violation.
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_user(self, user_id: uuid.UUID) -> Users:
        return await self._require_user(user_id)

    async def get_user_by_phone(self, phone: str) -> Users | None:
        return await self.users.get_user_by_phone(normalize_phone(phone))

    # ───────── Organizations ─────────
    async def create_organization(
        self,
        creator_id: uuid.UUID,
        data: OrganizationCreate,
    ) -> Organizations:
        try:
            await self._require_user(creator_id)

            if data.org_type not in self.SELF_SERVICE_ORG_TYPES:
                raise PermissionDeniedError(
                    "This organization type cannot be created here."
                )

            if await self.orgs.get_organization_by_name(data.name):
                raise OrganizationAlreadyExistsError(
                    "Organization name already taken."
                )

            org = await self.orgs.create_organization(
                name=data.name,
                org_type=data.org_type,
                address=data.address,
            )
            await self.memberships.create_membership(
                user_id=creator_id,
                organization_id=org.id,
                role=MembershipType.owner,
            )
            await self.session.commit()
            return org

        except IntegrityError:
            await self.session.rollback()
            # Preserve the real DB error until the actual constraint name is known.
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_organization(self, org_id: uuid.UUID) -> Organizations:
        return await self._require_org(org_id)

    async def get_user_organizations(
        self,
        user_id: uuid.UUID,
    ) -> list[tuple[Organizations, MembershipType]]:
        await self._require_user(user_id)
        return await self.orgs.get_user_organizations(user_id)

    async def verify_organization(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> Organizations:
        try:
            await self._require_platform_staff(actor_id)
            await self._require_org(org_id)

            org = await self.orgs.update_organization(org_id, verified=True)
            if org is None:
                raise OrganizationNotFoundError("Organization not found.")

            await self.session.commit()
            return org
        except Exception:
            await self.session.rollback()
            raise

    # ───────── Memberships ─────────
    async def add_member(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        data: MemberAdd,
    ) -> Memberships:
        try:
            await self._require_org(org_id)
            await self._require_owner(actor_id, org_id)

            target = await self.users.get_user_by_phone(normalize_phone(data.phone))
            if target is None:
                raise UserNotFoundError("No user with this phone number.")

            if await self.memberships.get_membership(target.id, org_id):
                raise MembershipAlreadyExistsError(
                    "User is already a member."
                )

            membership = await self.memberships.create_membership(
                user_id=target.id,
                organization_id=org_id,
                role=data.role,
            )
            await self.session.commit()
            return membership

        except IntegrityError:
            await self.session.rollback()
            # A concurrent duplicate may cause this; don't hide unrelated constraints.
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def change_member_role(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
        data: MemberRoleUpdate,
    ) -> Memberships:
        try:
            # Lock the parent organization before checking/changing owner count.
            await self._require_org_for_update(org_id)
            await self._require_owner(actor_id, org_id)

            target = await self.memberships.get_membership(
                target_user_id,
                org_id,
            )
            if target is None:
                raise MembershipNotFoundError(
                    "User is not a member of this organization."
                )

            if (
                target.role == MembershipType.owner
                and data.role != MembershipType.owner
            ):
                await self._ensure_not_last_owner(org_id)

            updated = await self.memberships.update_membership(
                target_user_id,
                org_id,
                role=data.role,
            )
            if updated is None:
                raise MembershipNotFoundError(
                    "User is not a member of this organization."
                )

            await self.session.commit()
            return updated

        except Exception:
            await self.session.rollback()
            raise

    async def remove_member(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """Owners can remove anyone; any member can remove themselves (leave)."""
        try:
            # Serializes owner-removal/role-demotion operations per organization.
            await self._require_org_for_update(org_id)

            target = await self.memberships.get_membership(
                target_user_id,
                org_id,
            )
            if target is None:
                raise MembershipNotFoundError(
                    "User is not a member of this organization."
                )

            if actor_id != target_user_id:
                await self._require_owner(actor_id, org_id)

            if target.role == MembershipType.owner:
                await self._ensure_not_last_owner(org_id)

            await self.memberships.delete_membership(target_user_id, org_id)
            await self.session.commit()

        except Exception:
            await self.session.rollback()
            raise

    async def list_members(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> list[Memberships]:
        await self._require_org(org_id)

        if await self.memberships.get_membership(actor_id, org_id) is None:
            raise PermissionDeniedError(
                "Only members can view the member list."
            )

        return await self.memberships.get_organization_memberships(org_id)

    # ───────── Internal helpers ─────────
    async def _require_user(self, user_id: uuid.UUID) -> Users:
        user = await self.users.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found.")
        return user

    async def _require_org(self, org_id: uuid.UUID) -> Organizations:
        org = await self.orgs.get_organization_by_id(org_id)
        if org is None:
            raise OrganizationNotFoundError("Organization not found.")
        return org

    async def _require_org_for_update(self, org_id: uuid.UUID) -> Organizations:
        org = await self.orgs.get_organization_for_update(org_id)
        if org is None:
            raise OrganizationNotFoundError("Organization not found.")
        return org

    async def _require_owner(
        self,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> None:
        membership = await self.memberships.get_membership(user_id, org_id)
        if membership is None or membership.role != MembershipType.owner:
            raise PermissionDeniedError("Only an owner can do this.")

    async def _ensure_not_last_owner(self, org_id: uuid.UUID) -> None:
        if await self.memberships.count_owners(org_id) <= 1:
            raise LastOwnerError(
                "An organization must keep at least one owner. "
                "Promote another member first."
            )

    async def _require_platform_staff(self, user_id: uuid.UUID) -> None:
        if not await self.memberships.user_is_platform_staff(user_id):
            raise PermissionDeniedError("Platform staff only.")

    # ───────── Authentication / Sessions ─────────
    async def login(
        self,
        user: Users,
        organization_id: uuid.UUID | None = None,
    ) -> TokenPair:
        try:
            memberships = await self.memberships.get_user_memberships(user.id)

            membership: Memberships | None = None
            if organization_id is not None:
                membership = next(
                    (
                        item
                        for item in memberships
                        if item.organization_id == organization_id
                    ),
                    None,
                )
                if membership is None:
                    raise PermissionDeniedError(
                        "You are not a member of this organization."
                    )
            elif memberships:
                # Existing behavior: select the oldest membership by creation time.
                membership = min(
                    memberships,
                    key=lambda item: item.created_at,
                )

            tokens = await self._issue_tokens(user.id, membership)
            await self.session.commit()
            return tokens

        except Exception:
            await self.session.rollback()
            raise

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Rotate a refresh token once; reject expired, unknown or reused tokens."""
        try:
            stored = await self.sessions.get_by_token_hash(
                hash_refresh_token(refresh_token)
            )
            if stored is None:
                raise InvalidRefreshTokenError("Invalid refresh token.")

            if stored.revoked_at is not None:
                # Reuse of a previously consumed token: revoke all user's sessions.
                await self.sessions.revoke_all_for_user(stored.user_id)
                await self.session.commit()
                raise InvalidRefreshTokenError(
                    "Refresh token reuse detected."
                )

            if stored.expires_at <= datetime.now(UTC):
                raise InvalidRefreshTokenError("Refresh token expired.")

            # This is an atomic UPDATE ... WHERE revoked_at IS NULL.
            if not await self.sessions.revoke_session(stored.id):
                await self.session.rollback()

                # Re-read after losing the race. If the token is now revoked,
                # treat it as reuse and revoke the user's remaining sessions.
                latest = await self.sessions.get_by_token_hash(
                    hash_refresh_token(refresh_token)
                )
                if latest is not None and latest.revoked_at is not None:
                    await self.sessions.revoke_all_for_user(latest.user_id)
                    await self.session.commit()

                raise InvalidRefreshTokenError(
                    "Refresh token already used."
                )

            membership = None
            if stored.organization_id is not None:
                membership = await self.memberships.get_membership(
                    stored.user_id,
                    stored.organization_id,
                )

            tokens = await self._issue_tokens(stored.user_id, membership)
            await self.session.commit()
            return tokens

        except InvalidRefreshTokenError:
            # Preserve an intentional commit performed by the reuse-detection path.
            # Rollback is safe after a commit and clears any remaining transaction.
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def logout(self, refresh_token: str) -> None:
        try:
            stored = await self.sessions.get_by_token_hash(
                hash_refresh_token(refresh_token)
            )
            if stored is not None:
                await self.sessions.revoke_session(stored.id)

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def get_current_user(self, user_id: uuid.UUID) -> Users:
        return await self._require_user(user_id)

    async def _issue_tokens(
        self,
        user_id: uuid.UUID,
        membership: Memberships | None,
    ) -> TokenPair:
        settings = get_settings()
        org_id = membership.organization_id if membership else None
        role = (
            MembershipType(membership.role).value
            if membership is not None
            else None
        )

        refresh = create_refresh_token()
        await self.sessions.create_session(
            user_id=user_id,
            organization_id=org_id,
            refresh_token_hash=hash_refresh_token(refresh),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_expire_days),
        )

        return TokenPair(
            access_token=create_access_token(user_id, org_id, role),
            refresh_token=refresh,
        )
