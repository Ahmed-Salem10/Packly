from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from packly.core.config import get_settings
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession

engine=create_async_engine(get_settings().database_url, echo=False, pool_pre_ping=True)

sessionlocal=async_sessionmaker(autocommit=False,expire_on_commit=False, autoflush=False, bind=engine)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with sessionlocal() as session:
        yield session