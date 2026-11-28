import base64
import json
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from packly.core.errors import AppError

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class PageParams:
    def __init__(self, after: str | None = None, limit: int = Query(20, ge=1, le=100)):
        self.after, self.limit = after, limit


def encode_cursor(row) -> str:
    raw = json.dumps({"t": row.created_at.isoformat(), "i": str(row.id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(s: str) -> tuple[datetime, UUID]:
    try:
        d = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
        return datetime.fromisoformat(d["t"]), UUID(d["i"])
    except Exception:
        raise AppError("invalid_cursor", "Invalid pagination cursor", 400)


async def paginate(session: AsyncSession, query: Select, model, *,
                   after: str | None = None, limit: int = 20, max_limit: int = 100) -> Page:
    limit = max(1, min(limit, max_limit))
    q = query.order_by(model.created_at.desc(), model.id.desc())
    if after:
        ts, id_ = decode_cursor(after)
        q = q.where(or_(model.created_at < ts, and_(model.created_at == ts, model.id < id_)))
    rows = (await session.execute(q.limit(limit + 1))).scalars().all()
    items = rows[:limit]
    return Page(items=items, next_cursor=encode_cursor(items[-1]) if len(rows) > limit else None)