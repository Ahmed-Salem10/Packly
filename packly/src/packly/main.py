from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(me_router)

    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}

    return app


app = create_app()
