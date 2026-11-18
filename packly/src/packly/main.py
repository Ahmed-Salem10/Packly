from fastapi import FastAPI
from packly.core.config import get_settings
from packly.core.logging import setup_logging


def create_app() -> FastAPI:
    app = FastAPI(title="Packly")
    settings=get_settings()
    setup_logging(level="INFO")
    
    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}
    
    return app