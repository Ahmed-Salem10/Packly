from fastapi import FastAPI
from packly.core.errors import register_exception_handlers
from packly.core.middleware import RequestIdMiddleware, access_log_middleware 
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from packly.core.logging import setup_logging
from packly.core.ratelimit import limiter
from packly.modules.identity.router import auth_router, me_router, router


def create_app() -> FastAPI:
    app = FastAPI(title="Packly")
    setup_logging(level="INFO")
    app.state.limiter = limiter

    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=access_log_middleware)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(me_router)

    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}

    return app


app = create_app()
