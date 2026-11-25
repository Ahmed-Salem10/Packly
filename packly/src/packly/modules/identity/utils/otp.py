import hashlib
import hmac
import logging
import re
import secrets

from packly.core.config import get_settings
from packly.core.redis import redis_client
from packly.modules.identity import normalize_phone

logger = logging.getLogger(__name__)


class OTPLocked(Exception):
    """Raised when the user has exceeded the maximum OTP attempts."""
    pass




def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(phone: str, otp: str) -> str:
    """
    Hash the OTP using HMAC-SHA256.

    The raw OTP is never stored in Redis.
    """
    settings = get_settings()

    secret_key = settings.otp_secret_key.get_secret_value()

    message = f"{phone}:{otp}".encode()

    return hmac.new(
        secret_key.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()



async def store_otp(phone: str, otp: str) -> None:
    settings = get_settings()

    # Don't reset failed attempts when requesting a new OTP.
    await redis_client.set(
        f"otp:{phone}",
        _hash_otp(phone, otp),
        ex=settings.otp_ttl,
    )

async def send_otp(phone: str, otp: str) -> None:
    settings = get_settings()

    if not settings.is_production:
        logger.info(
            "DEV ONLY - OTP for %s: %s",
            phone,
            otp,
        )
        return

    # Production provider integration
    raise NotImplementedError("Configure OTP provider")

async def _lock(phone: str) -> None:
    settings = get_settings()

    # Remove the current OTP and attempts.
    await redis_client.delete(
        f"otp:{phone}",
        f"otp_attempts:{phone}",
    )

    # Create a separate lock key.
    await redis_client.set(
        f"otp_lock:{phone}",
        "1",
        ex=settings.lock_seconds,
    )


async def verify_otp(phone: str, otp: str) -> bool:
    settings = get_settings()

    otp_key = f"otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"
    lock_key = f"otp_lock:{phone}"

    # 1. Check temporary lock.
    if await redis_client.exists(lock_key):
        raise OTPLocked()

    # 2. Get stored OTP.
    stored_hash = await redis_client.get(otp_key)

    if stored_hash is None:
        return False

    # 3. Compare hashes.
    provided_hash = _hash_otp(phone, otp)

    if hmac.compare_digest(stored_hash, provided_hash):

        # 4. Delete OTP after successful verification.
        deleted = await redis_client.delete(otp_key)

        if deleted == 1:
            await redis_client.delete(attempts_key)
            return True

        return False

    # 5. Increment failed attempts.
    attempts = await redis_client.incr(attempts_key)

    # Start the attempts expiration only once.
    if attempts == 1:
        await redis_client.expire(
            attempts_key,
            settings.otp_ttl,
        )

    # 6. Lock after reaching maximum attempts.
    if attempts >= settings.max_attempts:
        await _lock(phone)
        raise OTPLocked()

    return False
