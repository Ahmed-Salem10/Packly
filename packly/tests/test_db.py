import pytest
from sqlalchemy import text

from packly.core.db import sessionlocal


@pytest.mark.asyncio
async def test_db_connection():
    async with sessionlocal() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1