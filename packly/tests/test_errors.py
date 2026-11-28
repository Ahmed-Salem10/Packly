import asyncio
import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from starlette.middleware.base import BaseHTTPMiddleware

from packly.core.db import get_db
from packly.core.errors import AppError, register_exception_handlers
from packly.core.idempotency import IdemContext, IdempotencyKey, idempotency
from packly.core.middleware import RequestIdMiddleware, access_log_middleware
from packly.core.pagination import PageParams, paginate
from packly.modules.identity.models import Organizations


class OrgIn(BaseModel):
    name: str


def make_org(name: str) -> Organizations:
    return Organizations(name=name, type="buyer", address="test")


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=access_log_middleware)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise AppError("rfq_not_found", "RFQ not found", 404, {"id": "x"})

    @app.get("/crash")
    async def crash():
        raise RuntimeError("secret-internal-detail")

    @app.get("/orgs")
    async def orgs(p: PageParams = Depends(), session=Depends(get_db)):
        page = await paginate(
            session,
            select(Organizations).where(Organizations.name.like("pgtest-%")),
            Organizations,
            after=p.after,
            limit=p.limit,
        )
        return {"items": [str(o.id) for o in page.items], "next_cursor": page.next_cursor}

    @app.post("/orgs", status_code=201)
    async def create(payload: OrgIn, idem: IdemContext = Depends(idempotency), session=Depends(get_db)):
        if hit := await idem.begin(scope="test"):
            return hit
        org = make_org(payload.name)
        session.add(org)
        await session.flush()
        return await idem.complete(201, {"id": str(org.id), "name": org.name})

    return app


async def cleanup():
    async for s in get_db():
        await s.execute(delete(Organizations).where(Organizations.name.like("pgtest-%")))
        await s.execute(delete(IdempotencyKey).where(IdempotencyKey.scope == "test"))
        await s.commit()


async def count_orgs(name: str) -> int:
    async for s in get_db():
        return (
            await s.execute(select(func.count()).select_from(Organizations).where(Organizations.name == name))
        ).scalar_one()


@pytest.fixture
async def client():
    await cleanup()
    transport = ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await cleanup()


async def test_all_errors_same_shape(client):
    keys = {"code", "message", "details", "request_id"}
    r = await client.get("/boom")
    assert r.status_code == 404 and set(r.json()) == keys
    assert r.json()["request_id"] == r.headers["x-request-id"]

    r = await client.get("/crash")
    assert r.status_code == 500 and set(r.json()) == keys
    assert r.json()["code"] == "internal_error" and "secret" not in r.text

    r = await client.get("/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found" and set(r.json()) == keys

    r = await client.post("/orgs", json={}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


async def test_pagination_with_identical_timestamps(client):
    async for s in get_db():
        s.add_all([make_org(f"pgtest-{i:02d}") for i in range(25)])  # نفس created_at
        await s.commit()
    seen, after = [], None
    while True:
        params = {"limit": 10, **({"after": after} if after else {})}
        data = (await client.get("/orgs", params=params)).json()
        seen += data["items"]
        after = data["next_cursor"]
        if not after:
            break
    assert len(seen) == 25 and len(set(seen)) == 25

    r = await client.get("/orgs", params={"after": "garbage"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"


async def test_idempotency_replay_and_concurrency(client):
    name = f"pgtest-{uuid.uuid4().hex[:8]}"
    h = {"Idempotency-Key": uuid.uuid4().hex}
    r1 = await client.post("/orgs", json={"name": name}, headers=h)
    r2 = await client.post("/orgs", json={"name": name}, headers=h)
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert r2.headers["idempotent-replayed"] == "true"
    assert await count_orgs(name) == 1

    name2 = f"pgtest-{uuid.uuid4().hex[:8]}"
    h2 = {"Idempotency-Key": uuid.uuid4().hex}
    rs = await asyncio.gather(*[client.post("/orgs", json={"name": name2}, headers=h2) for _ in range(5)])
    assert {r.status_code for r in rs} == {201} and len({r.json()["id"] for r in rs}) == 1
    assert await count_orgs(name2) == 1


async def test_idempotency_misuse(client):
    r = await client.post("/orgs", json={"name": "pgtest-a"})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"

    h = {"Idempotency-Key": uuid.uuid4().hex}
    await client.post("/orgs", json={"name": "pgtest-a"}, headers=h)
    r = await client.post("/orgs", json={"name": "pgtest-b"}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reuse"