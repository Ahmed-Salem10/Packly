import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from packly.core.config import get_settings
from packly.core.db import get_db
from packly.core.ratelimit import limiter
from packly.main import app
from packly.modules.identity.models import Memberships, Organizations, Users
from packly.modules.identity.repository import UserRepository


@pytest_asyncio.fixture
async def db_session():
    # NullPool: every test gets its own connection on its own event loop.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    limiter.enabled = False  # rate limits live in Redis and would leak between runs
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    limiter.enabled = True


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    created: list[uuid.UUID] = []

    async def _make() -> Users:
        n = uuid.uuid4().int % 10**8
        user = await UserRepository(db_session).create_user(
            phone=f"+2010{n:08d}", name="Test User", email=f"t{uuid.uuid4().hex[:10]}@example.com"
        )
        await db_session.commit()
        created.append(user.id)
        return user

    yield _make

    # Cleanup: sessions and memberships go away via ON DELETE CASCADE.
    await db_session.rollback()
    rows = await db_session.execute(
        select(Memberships.organization_id).where(Memberships.user_id.in_(created))
    )
    org_ids = [r[0] for r in rows]
    await db_session.execute(delete(Users).where(Users.id.in_(created)))
    if org_ids:
        await db_session.execute(delete(Organizations).where(Organizations.id.in_(org_ids)))
    await db_session.commit()