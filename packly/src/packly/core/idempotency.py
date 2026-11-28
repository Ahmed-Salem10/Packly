import hashlib
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import String, UniqueConstraint, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from packly.core.db import get_db
from packly.core.errors import AppError
from packly.core.models import Base, IdMixin, TimestampMixin


class IdempotencyKey(Base, IdMixin, TimestampMixin):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)

    scope: Mapped[str] = mapped_column(String(64))          # عادةً user_id
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None]
    response_body: Mapped[dict | list | None] = mapped_column(JSONB)


@dataclass
class IdemContext:
    session: AsyncSession
    key: str
    request_hash: str
    _row_id: UUID | None = None
    _scope: str = ""

    async def begin(self, scope: str) -> JSONResponse | None:
        """None = طلب جديد كمّل شغلك. JSONResponse = ده replay، رجّعه زي ما هو."""
        self._scope = scope
        stmt = (
            pg_insert(IdempotencyKey)
            .values(scope=scope, key=self.key, request_hash=self.request_hash)
            .on_conflict_do_nothing(index_elements=["scope", "key"])
            .returning(IdempotencyKey.id)
        )
        self._row_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if self._row_id:
            return None

        row = (await self.session.execute(
            select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == self.key)
        )).scalar_one()
        if row.request_hash != self.request_hash:
            raise AppError("idempotency_key_reuse",
                           "Idempotency-Key was already used with a different request", 422)
        if row.status_code is None:
            raise AppError("idempotency_in_progress", "Original request is still processing", 409)
        return JSONResponse(row.response_body, status_code=row.status_code,
                            headers={"Idempotent-Replayed": "true"})

    async def complete(self, status_code: int, body) -> JSONResponse:
        """بيخزّن الرد ويعمل commit للشغل كله (الأثر + المفتاح) مع بعض."""
        body = jsonable_encoder(body)
        await self.session.execute(
            update(IdempotencyKey).where(IdempotencyKey.id == self._row_id)
            .values(status_code=status_code, response_body=body)
        )
        await self.session.commit()
        return JSONResponse(body, status_code=status_code)


async def idempotency(request: Request, session: AsyncSession = Depends(get_db)) -> IdemContext:
    key = request.headers.get("Idempotency-Key")
    if not key or len(key) > 255:
        raise AppError("idempotency_key_required",
                       "Idempotency-Key header is required (max 255 chars)", 400)
    raw = request.method.encode() + b"|" + request.url.path.encode() + b"|" + await request.body()
    return IdemContext(session, key, hashlib.sha256(raw).hexdigest())