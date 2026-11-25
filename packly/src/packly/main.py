from fastapi import FastAPI
from packly.core.config import get_settings
from packly.core.logging import setup_logging
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from packly.core.ratelimit import limiter


def create_app() -> FastAPI:
    app = FastAPI(title="Packly")
    settings=get_settings()
    setup_logging(level="INFO")
    app.state.limiter = limiter

    app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
    )

    
    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}
    
    return app

app = create_app()