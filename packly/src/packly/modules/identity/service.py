import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packly.modules.identity.models import (
    MembershipType,
    Memberships,
    OrgType,
    Organizations,
    Users,
)
from packly.modules.identity.utils.phone import normalize_phone
from packly.modules.identity.repository import (
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from packly.modules.identity.schemas import (
    MemberAdd,
    MemberRoleUpdate,
    OrganizationCreate,
    UserCreate,
)


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


# ───────────────────────── Service ─────────────────────────
class IdentityService:
    """Business rules for users, organizations and memberships.

    Input validation/normalization lives in schemas.py; this class receives
    already-validated schema objects. The service owns the transaction: it
    commits on success and rolls back on failure. Repositories only flush.
    """

    # Types a normal user may create. `staff` is internal (platform team).
    SELF_SERVICE_ORG_TYPES = {OrgType.buyer, OrgType.factory}

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)

    # ───────── Users ─────────
    async def register_user(self, data: UserCreate) -> Users:
        if await self.users.get_user_by_phone(data.phone):
            raise UserAlreadyExistsError("Phone number already registered.")
        if await self.users.get_user_by_email(data.email):
            raise UserAlreadyExistsError("Email already registered.")

        try:
            user = await self.users.create_user(
                phone=data.phone, name=data.name, email=data.email
            )
            await self.session.commit()
        except IntegrityError:
            # Lost a race with a concurrent signup.
            await self.session.rollback()
            raise UserAlreadyExistsError("Phone or email already registered.")
        return user

    async def get_user(self, user_id: uuid.UUID) -> Users:
        return await self._require_user(user_id)

    async def get_user_by_phone(self, phone: str) -> Users | None:
        return await self.users.get_user_by_phone(normalize_phone(phone))

    # ───────── Organizations ─────────
    async def create_organization(
        self, creator_id: uuid.UUID, data: OrganizationCreate
    ) -> Organizations:
        """Create an organization and make the creator its owner, atomically."""
        await self._require_user(creator_id)

        if data.org_type not in self.SELF_SERVICE_ORG_TYPES:
            raise PermissionDeniedError("This organization type cannot be created here.")

        if await self.orgs.get_organization_by_name(data.name):
            raise OrganizationAlreadyExistsError("Organization name already taken.")

        try:
            org = await self.orgs.create_organization(
                name=data.name, org_type=data.org_type, address=data.address
            )
            await self.memberships.create_membership(
                user_id=creator_id,
                organization_id=org.id,
                role=MembershipType.owner,
            )
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise OrganizationAlreadyExistsError("Organization name already taken.")
        return org

    async def get_organization(self, org_id: uuid.UUID) -> Organizations:
        return await self._require_org(org_id)

    async def get_user_organizations(
        self, user_id: uuid.UUID
    ) -> list[tuple[Organizations, MembershipType]]:
        await self._require_user(user_id)
        result = []
        for m in await self.memberships.get_user_memberships(user_id):
            org = await self.orgs.get_organization_by_id(m.organization_id)
            if org is not None:
                result.append((org, m.role))
        return result

    async def verify_organization(
        self, actor_id: uuid.UUID, org_id: uuid.UUID
    ) -> Organizations:
        """Only platform staff (member of a `staff` org) may verify."""
        await self._require_platform_staff(actor_id)
        await self._require_org(org_id)
        org = await self.orgs.update_organization(org_id, verified=True)
        await self.session.commit()
        return org

    # ───────── Memberships ─────────
    async def add_member(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        data: MemberAdd,
    ) -> Memberships:
        await self._require_org(org_id)
        await self._require_owner(actor_id, org_id)

        target = await self.users.get_user_by_phone(data.phone)
        if target is None:
            raise UserNotFoundError("No user with this phone number.")
        if await self.memberships.get_membership(target.id, org_id):
            raise MembershipAlreadyExistsError("User is already a member.")

        try:
            membership = await self.memberships.create_membership(
                user_id=target.id, organization_id=org_id, role=data.role
            )
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise MembershipAlreadyExistsError("User is already a member.")
        return membership

    async def change_member_role(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
        data: MemberRoleUpdate,
    ) -> Memberships:
        await self._require_owner(actor_id, org_id)
        target = await self.memberships.get_membership(target_user_id, org_id)
        if target is None:
            raise MembershipNotFoundError("User is not a member of this organization.")

        if target.role == MembershipType.owner and data.role != MembershipType.owner:
            await self._ensure_not_last_owner(org_id)

        updated = await self.memberships.update_membership(
            target_user_id, org_id, role=data.role
        )
        await self.session.commit()
        return updated

    async def remove_member(
        self,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """Owners can remove anyone; any member can remove themselves (leave)."""
        target = await self.memberships.get_membership(target_user_id, org_id)
        if target is None:
            raise MembershipNotFoundError("User is not a member of this organization.")

        if actor_id != target_user_id:
            await self._require_owner(actor_id, org_id)

        if target.role == MembershipType.owner:
            await self._ensure_not_last_owner(org_id)

        await self.memberships.delete_membership(target_user_id, org_id)
        await self.session.commit()

    async def list_members(
        self, actor_id: uuid.UUID, org_id: uuid.UUID
    ) -> list[Memberships]:
        await self._require_org(org_id)
        if await self.memberships.get_membership(actor_id, org_id) is None:
            raise PermissionDeniedError("Only members can view the member list.")
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

    async def _require_owner(self, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
        m = await self.memberships.get_membership(user_id, org_id)
        if m is None or m.role != MembershipType.owner:
            raise PermissionDeniedError("Only an owner can do this.")

    async def _ensure_not_last_owner(self, org_id: uuid.UUID) -> None:
        if await self.memberships.count_owners(org_id) <= 1:
            raise LastOwnerError(
                "An organization must keep at least one owner. "
                "Promote another member first."
            )

    async def _require_platform_staff(self, user_id: uuid.UUID) -> None:
        for m in await self.memberships.get_user_memberships(user_id):
            org = await self.orgs.get_organization_by_id(m.organization_id)
            if org is not None and org.type == OrgType.staff:
                return
        raise PermissionDeniedError("Platform staff only.")