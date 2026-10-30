from fastapi import FastAPI

from app.config.settings import get_settings
from app.features.core.health.endpoints import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name)
    app.include_router(health_router)
    return app


app = create_app()
