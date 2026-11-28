import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from packly.core.security import create_access_token, decode_token
from packly.modules.identity.deps import require_role
from packly.modules.identity.models import OrgType
from packly.modules.identity.schemas import OrganizationCreate
from packly.modules.identity.service import IdentityService
from packly.modules.identity.utils.otp import store_otp


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_me_returns_user_and_role(client, db_session, make_user):
    user = await make_user()
    service = IdentityService(db_session)
    org = await service.create_organization(
        user.id,
        OrganizationCreate(name=f"Org {uuid.uuid4().hex[:8]}", org_type=OrgType.buyer, address="Cairo"),
    )
    tokens = await service.login(user)

    r = await client.get("/v1/me", headers=auth(tokens.access_token))

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(user.id)
    assert body["role"] == "owner"
    assert body["organization_id"] == str(org.id)


@pytest.mark.asyncio
async def test_me_without_token_is_401(client):
    assert (await client.get("/v1/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token_is_401(client):
    assert (await client.get("/v1/me", headers=auth("not-a-jwt"))).status_code == 401


@pytest.mark.asyncio
async def test_me_expired_token_is_401(client):
    token = create_access_token(uuid.uuid4(), None, None, ttl=-1)
    r = await client.get("/v1/me", headers=auth(token))
    assert r.status_code == 401
    assert "expired" in r.json()["message"].lower()


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(client, db_session, make_user):
    user = await make_user()
    tokens = await IdentityService(db_session).login(user)

    r = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != tokens.refresh_token
    assert decode_token(new["access_token"]).user_id == user.id


@pytest.mark.asyncio
async def test_reused_refresh_token_is_401_and_revokes_family(client, db_session, make_user):
    user = await make_user()
    tokens = await IdentityService(db_session).login(user)

    first = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})
    assert first.status_code == 200
    newer = first.json()["refresh_token"]

    replay = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})
    assert replay.status_code == 401

    # The replay also killed the newer token (theft response).
    after = await client.post("/v1/auth/refresh", json={"refresh_token": newer})
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_unknown_refresh_token_is_401(client):
    r = await client.post("/v1/auth/refresh", json={"refresh_token": "x" * 64})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client, db_session, make_user):
    user = await make_user()
    tokens = await IdentityService(db_session).login(user)

    out = await client.post("/v1/auth/logout", json={"refresh_token": tokens.refresh_token})
    assert out.status_code == 204

    r = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})
    assert r.status_code == 401

    again = await client.post("/v1/auth/logout", json={"refresh_token": tokens.refresh_token})
    assert again.status_code == 204  # logging out twice is harmless


@pytest.mark.asyncio
async def test_wrong_role_is_403():
    mini = FastAPI()

    @mini.get("/admin", dependencies=[Depends(require_role("owner"))])
    async def admin():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://test") as c:
        viewer = create_access_token(uuid.uuid4(), uuid.uuid4(), "viewer")
        owner = create_access_token(uuid.uuid4(), uuid.uuid4(), "owner")

        assert (await c.get("/admin", headers=auth(viewer))).status_code == 403
        assert (await c.get("/admin", headers=auth(owner))).status_code == 200
        assert (await c.get("/admin")).status_code == 401


@pytest.mark.asyncio
async def test_otp_verify_issues_tokens(client, make_user):
    user = await make_user()
    await store_otp(user.phone, "123456")

    r = await client.post("/v1/auth/otp/verify", json={"phone": user.phone, "code": "123456"})

    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert decode_token(body["access_token"]).user_id == user.id
    me = await client.get("/v1/me", headers=auth(body["access_token"]))
    assert me.status_code == 200