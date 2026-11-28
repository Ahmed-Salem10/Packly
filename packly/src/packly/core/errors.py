import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()

HTTP_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 422: "unprocessable", 429: "rate_limited",
}


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400,
                 details: dict | list | None = None, headers: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details, self.headers = details, headers


class NotFound(AppError):
    def __init__(self, what: str = "resource", details=None):
        super().__init__("not_found", f"{what} not found", 404, details)


class Conflict(AppError):
    def __init__(self, message: str = "conflict", details=None):
        super().__init__("conflict", message, 409, details)


class Forbidden(AppError):
    def __init__(self, message: str = "forbidden"):
        super().__init__("forbidden", message, 403)


def error_response(request: Request, status: int, code: str, message: str,
                   details=None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": request.scope.get("state", {}).get("request_id"),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return error_response(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", "Invalid request", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(request, exc.status_code, code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled_error", path=request.url.path)
        return error_response(request, 500, "internal_error", "Internal server error")