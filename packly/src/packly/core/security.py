import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from packly.core.config import get_settings


class TokenError(Exception):
    """Raised when an access token is missing, malformed, expired or of the wrong type."""


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    role: str | None


# ───────────────────────── Access token (JWT) ─────────────────────────
def create_access_token(
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    role: str | None,
    ttl: int | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    if ttl is None:
        ttl = settings.access_token_expire_seconds

    claims = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        claims,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pin the algorithm
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if data.get("type") != "access":
        raise TokenError("Wrong token type")

    try:
        org = data.get("org")
        return TokenPayload(
            user_id=uuid.UUID(data["sub"]),
            org_id=uuid.UUID(org) if org else None,
            role=data.get("role"),
        )
    except ValueError as exc:
        raise TokenError("Invalid token claims") from exc


# ───────────────────────── Refresh token (opaque) ─────────────────────────
def create_refresh_token() -> str:
    """Random 384-bit string. It is NOT a JWT: the server only stores its hash."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    # The token already has high entropy, so a fast hash is enough (no bcrypt needed).
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), token_hash)