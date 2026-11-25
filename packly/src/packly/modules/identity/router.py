
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    status,
)

from packly.core.ratelimit import limiter
from packly.core.redis import redis_client

from packly.modules.identity.schemas import (
    OTPRequest,
    OTPVerify,
    OTPRequestResponse,
    OTPVerifyResponse,
)

from packly.modules.identity.utils.otp import (
    OTPLocked,
    generate_otp,
    store_otp,
    send_otp,
    verify_otp,
)

from packly.modules.identity.utils.phone import normalize_phone


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/v1/auth/otp",
    tags=["OTP Authentication"],
)


def mask_phone(phone: str) -> str:
    """Hide part of the phone number in logs."""
    return phone[:5] + "*****" + phone[-2:]


# ==========================================
# POST /v1/auth/otp/request
# ==========================================

@router.post(
    "/request",
    response_model=OTPRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("3/minute")
async def request_otp(
    payload: OTPRequest,
    request: Request,
    response: Response,
):
    """
    Generate, store and send an OTP.
    """

    # 1. Normalize phone number
    try:
        phone = normalize_phone(payload.phone)

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )

    # 2. Check if phone is temporarily locked
    lock_key = f"otp_lock:{phone}"

    if await redis_client.exists(lock_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
        )

    # 3. Per-phone cooldown (60 seconds)
    cooldown_key = f"otp_cooldown:{phone}"

    ok = await redis_client.set(
        cooldown_key,
        "1",
        nx=True,
        ex=60,
    )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before requesting another OTP.",
            headers={"Retry-After": "60"},
        )

    try:
        # 4. Generate OTP
        otp = generate_otp()

        # 5. Store hashed OTP in Redis
        await store_otp(phone, otp)

        # 6. Send OTP
        await send_otp(phone, otp)

    except Exception:
        # Rollback if sending or storing fails
        await redis_client.delete(
            cooldown_key,
            f"otp:{phone}",
        )
        raise

    logger.info(
        "OTP request processed for %s",
        mask_phone(phone),
    )

    return OTPRequestResponse(
        message="OTP has been sent successfully"
    )


# ==========================================
# POST /v1/auth/otp/verify
# ==========================================

@router.post(
    "/verify",
    response_model=OTPVerifyResponse,
)
@limiter.limit("5/minute")
async def verify_otp_endpoint(
    payload: OTPVerify,
    request: Request,
    response: Response,
):
    """
    Verify the OTP entered by the user.
    """

    # 1. Normalize phone number
    try:
        phone = normalize_phone(payload.phone)

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )

    # 2. Verify OTP
    try:
        is_valid = await verify_otp(
            phone=phone,
            otp=payload.code,
        )

    except OTPLocked:
        logger.warning(
            "OTP verification locked for %s",
            mask_phone(phone),
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
        )

    # 3. Reject invalid or expired OTP
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP",
        )

    # 4. OTP verified successfully
    logger.info(
        "OTP verified successfully for %s",
        mask_phone(phone),
    )

    return OTPVerifyResponse(
        message="OTP verified successfully",
        verified=True,
    )
