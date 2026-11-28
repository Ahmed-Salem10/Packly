
import uuid

import pytest

from packly.modules.identity.models import MembershipType, OrgType
from packly.modules.identity.schemas import (
    MemberAdd,
    MemberRoleUpdate,
    OrganizationCreate,
    UserCreate,
)
from packly.modules.identity.service import (
    IdentityService,
    LastOwnerError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
    PermissionDeniedError,
    UserAlreadyExistsError,
    UserNotFoundError,
)


def unique_name():
    return f"Test Org {uuid.uuid4().hex[:10]}"


# ==================== USER TESTS ====================

@pytest.mark.asyncio
async def test_register_user_success(db_session):
    service = IdentityService(db_session)

    data = UserCreate(
        phone=f"+2010{uuid.uuid4().int % 10**8:08d}",
        name="New User",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
    )

    user = await service.register_user(data)

    assert user.id is not None
    assert user.name == data.name
    assert user.phone == data.phone


@pytest.mark.asyncio
async def test_register_user_duplicate_phone(db_session, make_user):
    existing = await make_user()
    service = IdentityService(db_session)

    data = UserCreate(
        phone=existing.phone,
        name="Duplicate",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
    )

    with pytest.raises(UserAlreadyExistsError):
        await service.register_user(data)


@pytest.mark.asyncio
async def test_register_user_duplicate_email(db_session, make_user):
    existing = await make_user()
    service = IdentityService(db_session)

    data = UserCreate(
        phone=f"+2010{uuid.uuid4().int % 10**8:08d}",
        name="Duplicate",
        email=existing.email,
    )

    with pytest.raises(UserAlreadyExistsError):
        await service.register_user(data)


@pytest.mark.asyncio
async def test_get_user_missing(db_session):
    with pytest.raises(UserNotFoundError):
        await IdentityService(db_session).get_user(uuid.uuid4())


# ================= ORGANIZATION TESTS =================

@pytest.mark.asyncio
async def test_create_organization_success(db_session, make_user):
    user = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        user.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    membership = await service.memberships.get_membership(
        user.id, org.id
    )

    assert membership is not None
    assert membership.role == MembershipType.owner


@pytest.mark.asyncio
async def test_create_organization_rejects_staff(db_session, make_user):
    user = await make_user()

    with pytest.raises(PermissionDeniedError):
        await IdentityService(db_session).create_organization(
            user.id,
            OrganizationCreate(
                name=unique_name(),
                org_type=OrgType.staff,
                address="Cairo",
            ),
        )


@pytest.mark.asyncio
async def test_create_organization_duplicate_name(db_session, make_user):
    user = await make_user()
    service = IdentityService(db_session)

    data = OrganizationCreate(
        name=unique_name(),
        org_type=OrgType.buyer,
        address="Cairo",
    )

    await service.create_organization(user.id, data)

    with pytest.raises(OrganizationAlreadyExistsError):
        await service.create_organization(user.id, data)


@pytest.mark.asyncio
async def test_create_organization_missing_creator(db_session):
    with pytest.raises(UserNotFoundError):
        await IdentityService(db_session).create_organization(
            uuid.uuid4(),
            OrganizationCreate(
                name=unique_name(),
                org_type=OrgType.buyer,
                address="Cairo",
            ),
        )


@pytest.mark.asyncio
async def test_get_user_organizations(db_session, make_user):
    user = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        user.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    result = await service.get_user_organizations(user.id)

    assert len(result) == 1
    returned_org, role = result[0]
    assert returned_org.id == org.id
    assert role == MembershipType.owner


@pytest.mark.asyncio
async def test_get_organization_missing(db_session):
    with pytest.raises(OrganizationNotFoundError):
        await IdentityService(db_session).get_organization(uuid.uuid4())


# ================= MEMBERSHIP TESTS =================

@pytest.mark.asyncio
async def test_add_member_success(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    membership = await service.add_member(
        owner.id,
        org.id,
        MemberAdd(
            phone=target.phone,
            role=MembershipType.member,
        ),
    )

    assert membership.user_id == target.id
    assert membership.role == MembershipType.member


@pytest.mark.asyncio
async def test_add_member_rejects_non_owner(db_session, make_user):
    owner = await make_user()
    outsider = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    with pytest.raises(PermissionDeniedError):
        await service.add_member(
            outsider.id,
            org.id,
            MemberAdd(
                phone=outsider.phone,
                role=MembershipType.member,
            ),
        )


@pytest.mark.asyncio
async def test_add_member_unknown_phone(db_session, make_user):
    owner = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    with pytest.raises(UserNotFoundError):
        await service.add_member(
            owner.id,
            org.id,
            MemberAdd(
                phone="+201099999999",
                role=MembershipType.member,
            ),
        )


@pytest.mark.asyncio
async def test_add_member_duplicate(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    data = MemberAdd(
        phone=target.phone,
        role=MembershipType.member,
    )

    await service.add_member(owner.id, org.id, data)

    with pytest.raises(MembershipAlreadyExistsError):
        await service.add_member(owner.id, org.id, data)


@pytest.mark.asyncio
async def test_change_member_role_success(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    await service.add_member(
        owner.id,
        org.id,
        MemberAdd(
            phone=target.phone,
            role=MembershipType.member,
        ),
    )

    updated = await service.change_member_role(
        owner.id,
        org.id,
        target.id,
        MemberRoleUpdate(role=MembershipType.viewer),
    )

    assert updated.role == MembershipType.viewer


@pytest.mark.asyncio
async def test_change_member_role_rejects_non_owner(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    await service.add_member(
        owner.id,
        org.id,
        MemberAdd(
            phone=target.phone,
            role=MembershipType.member,
        ),
    )

    with pytest.raises(PermissionDeniedError):
        await service.change_member_role(
            target.id,
            org.id,
            target.id,
            MemberRoleUpdate(role=MembershipType.viewer),
        )


@pytest.mark.asyncio
async def test_cannot_demote_last_owner(db_session, make_user):
    owner = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    with pytest.raises(LastOwnerError):
        await service.change_member_role(
            owner.id,
            org.id,
            owner.id,
            MemberRoleUpdate(role=MembershipType.member),
        )


@pytest.mark.asyncio
async def test_remove_member_success(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    await service.add_member(
        owner.id,
        org.id,
        MemberAdd(
            phone=target.phone,
            role=MembershipType.member,
        ),
    )

    await service.remove_member(owner.id, org.id, target.id)

    assert await service.memberships.get_membership(
        target.id, org.id
    ) is None


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(db_session, make_user):
    owner = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    with pytest.raises(LastOwnerError):
        await service.remove_member(owner.id, org.id, owner.id)


@pytest.mark.asyncio
async def test_list_members_requires_membership(db_session, make_user):
    owner = await make_user()
    outsider = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    with pytest.raises(PermissionDeniedError):
        await service.list_members(outsider.id, org.id)


@pytest.mark.asyncio
async def test_list_members_success(db_session, make_user):
    owner = await make_user()
    target = await make_user()
    service = IdentityService(db_session)

    org = await service.create_organization(
        owner.id,
        OrganizationCreate(
            name=unique_name(),
            org_type=OrgType.buyer,
            address="Cairo",
        ),
    )

    await service.add_member(
        owner.id,
        org.id,
        MemberAdd(
            phone=target.phone,
            role=MembershipType.member,
        ),
    )

    members = await service.list_members(owner.id, org.id)

    assert len(members) == 2
