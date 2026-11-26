import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from packly.core.db import get_db
from packly.core.security import TokenError, decode_token
from packly.modules.identity.service import IdentityService

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    org_id: uuid.UUID | None
    role: str | None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc
    return CurrentUser(id=payload.user_id, org_id=payload.org_id, role=payload.role)


def require_role(*roles: str | Enum):
    """Usage: dependencies=[Depends(require_role("owner"))]"""
    allowed = {r.value if isinstance(r, Enum) else r for r in roles}

    async def checker(
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
            )
        return user

    return checker


async def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IdentityService:
    return IdentityService(session)
