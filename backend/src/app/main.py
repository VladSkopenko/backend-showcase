from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.error_responses import domain_error_response
from app.common.errors import DomainError
from app.config.settings import get_settings
from app.features.core.auth.endpoints import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.endpoints import router as auth_router
from app.features.core.health.endpoints import router as health_router

ERROR_STATUSES = {**AUTH_ERROR_STATUSES}


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app.name)
    app.include_router(health_router)
    app.include_router(auth_router)

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return domain_error_response(exc, ERROR_STATUSES)

    return app


app = create_app()
