from fastapi import FastAPI
from packly.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Packly")
    settings=get_settings()

    
    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}
    
    return app