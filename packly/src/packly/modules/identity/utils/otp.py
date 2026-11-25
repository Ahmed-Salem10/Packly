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
    """
    Store the hashed OTP in Redis with an expiration time.

    Also resets previous failed attempts.
    """
    settings = get_settings()

    phone = normalize_phone(phone)

    otp_key = f"otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"

    await redis_client.set(
        otp_key,
        _hash_otp(phone, otp),
        ex=settings.otp_ttl,
    )

    await redis_client.delete(attempts_key)


async def send_otp(phone: str, otp: str) -> None:
    settings = get_settings()

    if not settings.is_production:
        logger.info("DEV OTP | phone=%s | code=%s", phone, otp)
        return

    # Production:
    # await whatsapp_provider.send_otp(phone, otp)

    raise NotImplementedError(
        "Configure OTP provider for production"
    )


async def _lock(phone: str) -> None:
    """
    Lock OTP verification for the configured lock duration.

    The OTP and attempts counter are deleted so the current OTP
    cannot be used after the account is locked.
    """
    settings = get_settings()

    phone = normalize_phone(phone)

    otp_key = f"otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"
    lock_key = f"otp_lock:{phone}"

    await redis_client.delete(
        otp_key,
        attempts_key,
    )

    await redis_client.set(
        lock_key,
        "1",
        ex=settings.lock_seconds,
    )


async def verify_otp(phone: str, otp: str) -> bool:
    """
    Verify an OTP.

    Returns:
        True  -> OTP is valid.
        False -> OTP is invalid or expired.

    Raises:
        OTPLocked -> maximum failed attempts reached.
    """
    settings = get_settings()

    phone = normalize_phone(phone)

    otp_key = f"otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"
    lock_key = f"otp_lock:{phone}"

    # 1. Check whether the user is currently locked.
    if await redis_client.exists(lock_key):
        raise OTPLocked()

    # 2. Check current failed attempts.
    attempts = await redis_client.get(attempts_key)

    if attempts is not None and int(attempts) >= settings.max_attempts:
        await _lock(phone)
        raise OTPLocked()

    # 3. Get stored OTP hash.
    stored_hash = await redis_client.get(otp_key)

    if stored_hash is None:
        logger.warning(
            "No OTP found for %s",
            phone,
        )
        return False

    # 4. Hash the OTP entered by the user.
    provided_hash = _hash_otp(phone, otp)

    # 5. Compare hashes securely.
    if hmac.compare_digest(stored_hash, provided_hash):

        # Delete OTP immediately so it can only be used once.
        deleted = await redis_client.delete(otp_key)

        if deleted == 1:
            await redis_client.delete(attempts_key)
            return True

        return False

    # 6. Wrong OTP → increment failed attempts.
    attempts = await redis_client.incr(attempts_key)

    # Set expiration on the attempts counter.
    if attempts == 1:
        await redis_client.expire(
            attempts_key,
            settings.lock_seconds,
        )

    logger.warning(
        "Invalid OTP attempt for %s. Attempt %s/%s",
        phone,
        attempts,
        settings.max_attempts,
    )

    # 7. Maximum attempts reached → lock the user.
    if attempts >= settings.max_attempts:
        await _lock(phone)
        raise OTPLocked()

    return False
