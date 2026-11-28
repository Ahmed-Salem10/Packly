
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from packly.modules.identity.models import MembershipType, OrgType
from packly.modules.identity.repository import (
    MembershipRepository,
    OrganizationRepository,
    SessionRepository,
    UserRepository,
)


def unique_name():
    return f"Repository Org {uuid.uuid4().hex[:10]}"


# ================= USER REPOSITORY =================

@pytest.mark.asyncio
async def test_user_create_and_get(db_session):
    repo = UserRepository(db_session)

    phone = f"+2010{uuid.uuid4().int % 10**8:08d}"
    email = f"{uuid.uuid4().hex[:12]}@example.com"

    user = await repo.create_user(phone, "Test User", email)

    assert (await repo.get_user_by_id(user.id)).id == user.id
    assert (await repo.get_user_by_phone(phone)).id == user.id
    assert (await repo.get_user_by_email(email)).id == user.id


@pytest.mark.asyncio
async def test_user_update(db_session, make_user):
    user = await make_user()
    repo = UserRepository(db_session)

    updated = await repo.update_user(user.id, name="Updated")

    assert updated.name == "Updated"


@pytest.mark.asyncio
async def test_user_update_rejects_invalid_field(db_session, make_user):
    user = await make_user()

    with pytest.raises(ValueError):
        await UserRepository(db_session).update_user(
            user.id, is_admin=True
        )


@pytest.mark.asyncio
async def test_user_delete(db_session, make_user):
    user = await make_user()
    repo = UserRepository(db_session)

    await repo.delete_user(user.id)

    assert await repo.get_user_by_id(user.id) is None


# ================= ORGANIZATION REPOSITORY =================

@pytest.mark.asyncio
async def test_organization_create_and_get(db_session):
    repo = OrganizationRepository(db_session)

    org = await repo.create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    assert (await repo.get_organization_by_id(org.id)).id == org.id
    assert (await repo.get_organization_by_name(org.name)).id == org.id


@pytest.mark.asyncio
async def test_organization_for_update(db_session):
    repo = OrganizationRepository(db_session)

    org = await repo.create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    locked = await repo.get_organization_for_update(org.id)

    assert locked is not None
    assert locked.id == org.id


@pytest.mark.asyncio
async def test_organization_update(db_session):
    repo = OrganizationRepository(db_session)

    org = await repo.create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    updated = await repo.update_organization(
        org.id,
        address="Alexandria",
        verified=True,
    )

    assert updated.address == "Alexandria"
    assert updated.verified is True


@pytest.mark.asyncio
async def test_organization_update_rejects_invalid_field(db_session):
    repo = OrganizationRepository(db_session)

    org = await repo.create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    with pytest.raises(ValueError):
        await repo.update_organization(org.id, type=OrgType.staff)


# ================= MEMBERSHIP REPOSITORY =================

@pytest.mark.asyncio
async def test_membership_create_and_get(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    membership = await repo.create_membership(
        user.id, org.id, MembershipType.owner
    )

    found = await repo.get_membership(user.id, org.id)

    assert found.id == membership.id
    assert found.role == MembershipType.owner


@pytest.mark.asyncio
async def test_membership_lists(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.owner
    )

    assert len(await repo.get_user_memberships(user.id)) == 1
    assert len(await repo.get_organization_memberships(org.id)) == 1


@pytest.mark.asyncio
async def test_count_owners(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.owner
    )

    assert await repo.count_owners(org.id) == 1


@pytest.mark.asyncio
async def test_platform_staff_lookup(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.staff, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.member
    )

    assert await repo.user_is_platform_staff(user.id) is True
    assert await repo.user_is_platform_staff(uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_membership_update(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.member
    )

    updated = await repo.update_membership(
        user.id, org.id, role=MembershipType.viewer
    )

    assert updated.role == MembershipType.viewer


@pytest.mark.asyncio
async def test_membership_update_rejects_invalid_field(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.member
    )

    with pytest.raises(ValueError):
        await repo.update_membership(
            user.id,
            org.id,
            invalid_field="invalid",
        )

@pytest.mark.asyncio
async def test_membership_delete(db_session, make_user):
    user = await make_user()
    org = await OrganizationRepository(db_session).create_organization(
        unique_name(), OrgType.buyer, "Cairo"
    )

    repo = MembershipRepository(db_session)

    await repo.create_membership(
        user.id, org.id, MembershipType.member
    )

    await repo.delete_membership(user.id, org.id)

    assert await repo.get_membership(user.id, org.id) is None


# ================= SESSION REPOSITORY =================

@pytest.mark.asyncio
async def test_session_create_get_and_revoke(db_session, make_user):
    user = await make_user()
    repo = SessionRepository(db_session)
    token_hash = uuid.uuid4().hex

    session = await repo.create_session(
        user_id=user.id,
        organization_id=None,
        refresh_token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    found = await repo.get_by_token_hash(token_hash)

    assert found.id == session.id
    assert await repo.revoke_session(session.id) is True
    assert await repo.revoke_session(session.id) is False


@pytest.mark.asyncio
async def test_revoke_all_sessions(db_session, make_user):
    user = await make_user()
    repo = SessionRepository(db_session)
    expires = datetime.now(UTC) + timedelta(days=1)

    first = await repo.create_session(
        user.id, None, uuid.uuid4().hex, expires
    )
    second = await repo.create_session(
        user.id, None, uuid.uuid4().hex, expires
    )

    await repo.revoke_all_for_user(user.id)

    await db_session.refresh(first)
    await db_session.refresh(second)

    assert first.revoked_at is not None
    assert second.revoked_at is not None
