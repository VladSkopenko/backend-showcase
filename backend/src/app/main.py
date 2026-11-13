from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.common.error_responses import (
    domain_error_response,
    http_error_response,
    server_error_response,
    validation_error_response,
)
from app.common.errors import DomainError
from app.config.settings import get_settings
from app.features.core.auth.endpoints import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.endpoints import AuthOpenApiTags, oauth_router
from app.features.core.auth.endpoints import router as auth_router
from app.features.core.bookings.endpoints import ERROR_STATUSES as BOOKINGS_ERROR_STATUSES
from app.features.core.bookings.endpoints import BookingOpenApiTags
from app.features.core.bookings.endpoints import router as bookings_router
from app.features.core.health.endpoints import HealthOpenApiTags
from app.features.core.health.endpoints import router as health_router
from app.features.core.locations.endpoints import ERROR_STATUSES as LOCATIONS_ERROR_STATUSES
from app.features.core.locations.endpoints import LocationsOpenApiTags
from app.features.core.locations.endpoints import router as locations_router
from app.features.core.menu.endpoints import ERROR_STATUSES as MENU_ERROR_STATUSES
from app.features.core.menu.endpoints import MenuOpenApiTags
from app.features.core.menu.endpoints import router as menu_router
from app.features.invites.endpoints import ERROR_STATUSES as INVITES_ERROR_STATUSES
from app.features.invites.endpoints import InvitesOpenApiTags
from app.features.invites.endpoints import router as invites_router
from app.features.preorder.endpoints import ERROR_STATUSES as PREORDER_ERROR_STATUSES
from app.features.preorder.endpoints import PreorderOpenApiTags
from app.features.preorder.endpoints import router as preorder_router
from app.infrastructure.oauth import OAuthClients

ERROR_STATUSES = {
    **AUTH_ERROR_STATUSES,
    **MENU_ERROR_STATUSES,
    **LOCATIONS_ERROR_STATUSES,
    **BOOKINGS_ERROR_STATUSES,
    **INVITES_ERROR_STATUSES,
    **PREORDER_ERROR_STATUSES,
}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app.name,
        openapi_tags=[
            *AuthOpenApiTags.METADATA,
            *MenuOpenApiTags.METADATA,
            *LocationsOpenApiTags.METADATA,
            *BookingOpenApiTags.METADATA,
            *InvitesOpenApiTags.METADATA,
            *PreorderOpenApiTags.METADATA,
            *HealthOpenApiTags.METADATA,
        ],
    )
    app.state.oauth_clients = OAuthClients(google=settings.google)
    # Holds only the OAuth state, nonce and PKCE verifier between /login and /callback.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.token.secret_key.get_secret_value(),
        session_cookie="oauth_state",
        max_age=settings.auth.oauth_state_max_age_seconds,
        path=settings.auth.oauth_state_cookie_path,
        same_site="lax",
        https_only=True,
    )
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(oauth_router, prefix="/api/v1")
    app.include_router(menu_router, prefix="/api/v1")
    app.include_router(locations_router, prefix="/api/v1")
    app.include_router(bookings_router, prefix="/api/v1")
    app.include_router(invites_router, prefix="/api/v1")
    app.include_router(preorder_router, prefix="/api/v1")

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return domain_error_response(exc, ERROR_STATUSES)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return validation_error_response(exc)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return http_error_response(exc)

    # Starlette re-raises the exception after sending this response, and the server logs it.
    @app.exception_handler(Exception)
    async def handle_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        return server_error_response()

    return app


app = create_app()
