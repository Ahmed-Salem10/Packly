
import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    status,
)

from packly.core.ratelimit import limiter

from packly.modules.identity.schemas import (
    OTPRequest,
    OTPVerify,
    OTPRequestResponse,
    OTPVerifyResponse,
)

from packly.modules.identity.utils.otp import (
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
    Generate and send a new OTP to the user's phone.
    """

    # 1. Normalize phone number
    try:
        phone = normalize_phone(payload.phone)

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )

    # 2. Generate OTP
    otp = generate_otp(phone)

    # 3. Store hashed OTP in Redis
    await store_otp(phone, otp)

    # 4. Send OTP (DEV: terminal logs)
    await send_otp(phone, otp)

    logger.info("OTP request processed for %s", phone)

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
    is_valid = await verify_otp(
        phone=phone,
        otp=payload.code,
    )

    # 3. Reject invalid or expired OTP
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP",
        )

    # 4. OTP verified successfully
    return OTPVerifyResponse(
        message="OTP verified successfully",
        verified=True,
    )
