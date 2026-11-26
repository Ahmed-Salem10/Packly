import uuid

import jwt
import pytest

from packly.core.config import get_settings
from packly.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_refresh_token,
    verify_refresh_token,
)


def test_access_token_roundtrip():
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    payload = decode_token(create_access_token(user_id, org_id, "owner"))
    assert payload.user_id == user_id
    assert payload.org_id == org_id
    assert payload.role == "owner"


def test_access_token_without_org():
    payload = decode_token(create_access_token(uuid.uuid4(), None, None))
    assert payload.org_id is None
    assert payload.role is None


def test_expired_token_rejected():
    token = create_access_token(uuid.uuid4(), None, None, ttl=-1)
    with pytest.raises(TokenError, match="expired"):
        decode_token(token)


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c"])
def test_garbage_token_rejected(bad):
    with pytest.raises(TokenError):
        decode_token(bad)


def test_token_signed_with_other_key_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": 9999999999}, "x" * 40, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        decode_token(forged)


def test_alg_none_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": 9999999999}, None, algorithm="none"
    )
    with pytest.raises(TokenError):
        decode_token(forged)


def test_wrong_token_type_rejected():
    secret = get_settings().jwt_secret_key.get_secret_value()
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "exp": 9999999999}, secret, algorithm="HS256"
    )
    with pytest.raises(TokenError, match="type"):
        decode_token(token)


def test_refresh_token_hashing():
    token = create_refresh_token()
    token_hash = hash_refresh_token(token)
    assert token != token_hash
    assert len(token_hash) == 64
    assert verify_refresh_token(token, token_hash)
    assert not verify_refresh_token(token + "x", token_hash)
    assert create_refresh_token() != token