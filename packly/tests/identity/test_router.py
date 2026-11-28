
from unittest.mock import AsyncMock

import pytest

import packly.modules.identity.router as router_module


class FakeRedis:
    def __init__(self, exists_result=False, set_result=True):
        self.exists_result = exists_result
        self.set_result = set_result
        self.deleted_keys = []
        self.set_calls = []

    async def exists(self, key):
        return self.exists_result

    async def set(self, key, value, nx=False, ex=None):
        self.set_calls.append((key, value, nx, ex))
        return self.set_result

    async def delete(self, *keys):
        self.deleted_keys.extend(keys)
        return len(keys)


@pytest.mark.asyncio
async def test_otp_request_success(client, monkeypatch):
    fake_redis = FakeRedis()

    monkeypatch.setattr(router_module, "redis_client", fake_redis)
    monkeypatch.setattr(router_module, "generate_otp", lambda: "123456")

    store_mock = AsyncMock()
    send_mock = AsyncMock()

    monkeypatch.setattr(router_module, "store_otp", store_mock)
    monkeypatch.setattr(router_module, "send_otp", send_mock)

    response = await client.post(
        "/v1/auth/otp/request",
        json={"phone": "+201012345678"},
    )

    assert response.status_code == 202
    assert response.json()["message"] == "OTP has been sent successfully"

    store_mock.assert_awaited_once_with("+201012345678", "123456")
    send_mock.assert_awaited_once_with("+201012345678", "123456")

    assert fake_redis.set_calls[0][2:] == (True, 60)


@pytest.mark.asyncio
async def test_otp_request_rejects_locked_phone(client, monkeypatch):
    fake_redis = FakeRedis(exists_result=True)
    monkeypatch.setattr(router_module, "redis_client", fake_redis)

    response = await client.post(
        "/v1/auth/otp/request",
        json={"phone": "+201012345678"},
    )

    assert response.status_code == 429
    assert "Too many failed attempts" in response.json()["message"]


@pytest.mark.asyncio
async def test_otp_request_rejects_cooldown(client, monkeypatch):
    fake_redis = FakeRedis(set_result=False)
    monkeypatch.setattr(router_module, "redis_client", fake_redis)

    response = await client.post(
        "/v1/auth/otp/request",
        json={"phone": "+201012345678"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_otp_request_cleans_up_when_sending_fails(client, monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(router_module, "redis_client", fake_redis)

    monkeypatch.setattr(router_module, "generate_otp", lambda: "123456")
    monkeypatch.setattr(
        router_module,
        "store_otp",
        AsyncMock(),
    )

    send_mock = AsyncMock(side_effect=RuntimeError("SMS provider failed"))
    monkeypatch.setattr(router_module, "send_otp", send_mock)

    with pytest.raises(RuntimeError, match="SMS provider failed"):
        await client.post(
            "/v1/auth/otp/request",
            json={"phone": "+201012345678"},
        )

    assert "otp_cooldown:+201012345678" in fake_redis.deleted_keys
    assert "otp:+201012345678" in fake_redis.deleted_keys


@pytest.mark.asyncio
async def test_otp_verify_rejects_invalid_code(client, monkeypatch):
    verify_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(router_module, "verify_otp", verify_mock)

    response = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": "+201012345678",
            "code": "000000",
        },
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid or expired OTP"


@pytest.mark.asyncio
async def test_otp_verify_rejects_locked_attempts(client, monkeypatch):
    verify_mock = AsyncMock(
        side_effect=router_module.OTPLocked()
    )
    monkeypatch.setattr(router_module, "verify_otp", verify_mock)

    response = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": "+201012345678",
            "code": "000000",
        },
    )

    assert response.status_code == 429
    assert "Too many failed attempts" in response.json()["message"]


@pytest.mark.asyncio
async def test_otp_verify_returns_404_for_unknown_phone(client, monkeypatch):
    monkeypatch.setattr(
        router_module,
        "verify_otp",
        AsyncMock(return_value=True),
    )

    response = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": "+201012345678",
            "code": "123456",
        },
    )

    assert response.status_code == 404
    assert response.json()["message"] == "Phone number is not registered"
