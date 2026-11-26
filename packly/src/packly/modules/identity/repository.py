import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packly.modules.identity.models import (
    Memberships,
    MembershipType,
    Organizations,
    OrgType,
    Sessions,
    Users,
)


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        phone: str,
        name: str,
        email: str | None,
    ) -> Users:
        new_user = Users(phone=phone, name=name, email=email)
        self.session.add(new_user)
        await self.session.flush()
        return new_user

    async def get_user_by_phone(self, phone: str) -> Users | None:
        result = await self.session.execute(
            select(Users).where(Users.phone == phone)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> Users | None:
        result = await self.session.execute(
            select(Users).where(Users.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Users | None:
        result = await self.session.execute(
            select(Users).where(Users.email == email)
        )
        return result.scalar_one_or_none()

    async def update_user(
        self,
        user_id: uuid.UUID,
        **kwargs,
    ) -> Users | None:
        allowed_fields = {"name", "email", "phone"}
        invalid = set(kwargs) - allowed_fields
        if invalid:
            raise ValueError(f"Fields cannot be updated: {sorted(invalid)}")

        if kwargs:
            await self.session.execute(
                update(Users)
                .where(Users.id == user_id)
                .values(**kwargs)
            )
            await self.session.flush()

        return await self.get_user_by_id(user_id)

    async def delete_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(Users).where(Users.id == user_id)
        )
        await self.session.flush()


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_organization(
        self,
        name: str,
        org_type: OrgType,
        address: str,
    ) -> Organizations:
        new_org = Organizations(
            name=name,
            type=org_type,
            address=address,
        )
        self.session.add(new_org)
        await self.session.flush()
        return new_org

    async def get_organization_by_id(
        self,
        org_id: uuid.UUID,
    ) -> Organizations | None:
        result = await self.session.execute(
            select(Organizations).where(Organizations.id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_organization_for_update(
        self,
        org_id: uuid.UUID,
    ) -> Organizations | None:
        """Lock the organization row until the current transaction completes."""
        result = await self.session.execute(
            select(Organizations)
            .where(Organizations.id == org_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_organization_by_name(
        self,
        name: str,
    ) -> Organizations | None:
        result = await self.session.execute(
            select(Organizations).where(Organizations.name == name)
        )
        return result.scalar_one_or_none()

    async def get_user_organizations(
        self,
        user_id: uuid.UUID,
    ) -> list[tuple[Organizations, MembershipType]]:
        result = await self.session.execute(
            select(Organizations, Memberships.role)
            .join(
                Memberships,
                Memberships.organization_id == Organizations.id,
            )
            .where(Memberships.user_id == user_id)
        )
        return [
            (organization, MembershipType(role))
            for organization, role in result.all()
        ]

    async def update_organization(
        self,
        org_id: uuid.UUID,
        **kwargs,
    ) -> Organizations | None:
        allowed_fields = {"name", "address", "verified"}
        invalid = set(kwargs) - allowed_fields
        if invalid:
            raise ValueError(f"Fields cannot be updated: {sorted(invalid)}")

        if kwargs:
            await self.session.execute(
                update(Organizations)
                .where(Organizations.id == org_id)
                .values(**kwargs)
            )
            await self.session.flush()

        return await self.get_organization_by_id(org_id)

    async def delete_organization(self, org_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(Organizations).where(Organizations.id == org_id)
        )
        await self.session.flush()


class MembershipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_membership(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        role: MembershipType,
    ) -> Memberships:
        membership = Memberships(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def get_membership(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Memberships | None:
        result = await self.session.execute(
            select(Memberships).where(
                Memberships.user_id == user_id,
                Memberships.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_memberships(
        self,
        user_id: uuid.UUID,
    ) -> list[Memberships]:
        result = await self.session.execute(
            select(Memberships).where(Memberships.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_organization_memberships(
        self,
        organization_id: uuid.UUID,
    ) -> list[Memberships]:
        result = await self.session.execute(
            select(Memberships).where(
                Memberships.organization_id == organization_id
            )
        )
        return list(result.scalars().all())

    async def delete_membership(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:
        await self.session.execute(
            delete(Memberships).where(
                Memberships.user_id == user_id,
                Memberships.organization_id == organization_id,
            )
        )
        await self.session.flush()

    async def count_owners(self, organization_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Memberships)
            .where(
                Memberships.organization_id == organization_id,
                Memberships.role == MembershipType.owner,
            )
        )
        return result.scalar_one()

    async def user_is_platform_staff(self, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(Memberships.user_id)
            .join(
                Organizations,
                Organizations.id == Memberships.organization_id,
            )
            .where(
                Memberships.user_id == user_id,
                Organizations.type == OrgType.staff,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    _UPDATABLE_FIELDS: ClassVar[set[str]] = {"role"}

    async def update_membership(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        **kwargs,
    ) -> Memberships | None:
        invalid = set(kwargs) - self._UPDATABLE_FIELDS
        if invalid:
            raise ValueError(f"Fields cannot be updated: {sorted(invalid)}")

        if kwargs:
            await self.session.execute(
                update(Memberships)
                .where(
                    Memberships.user_id == user_id,
                    Memberships.organization_id == organization_id,
                )
                .values(**kwargs)
            )
            await self.session.flush()

        return await self.get_membership(user_id, organization_id)


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> Sessions:
        new_session = Sessions(
            user_id=user_id,
            organization_id=organization_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
        )
        self.session.add(new_session)
        await self.session.flush()
        return new_session

    async def get_by_token_hash(self, token_hash: str) -> Sessions | None:
        result = await self.session.execute(
            select(Sessions).where(
                Sessions.refresh_token_hash == token_hash
            )
        )
        return result.scalar_one_or_none()

    async def revoke_session(self, session_id: uuid.UUID) -> bool:
        """Atomically revoke only if the session is not already revoked."""
        result = await self.session.execute(
            update(Sessions)
            .where(
                Sessions.id == session_id,
                Sessions.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
            .returning(Sessions.id)
        )
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Sessions)
            .where(
                Sessions.user_id == user_id,
                Sessions.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        await self.session.flush()
