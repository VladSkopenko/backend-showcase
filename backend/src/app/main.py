from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.common.error_responses import domain_error_response
from app.common.errors import DomainError
from app.config.settings import get_settings
from app.features.core.auth.endpoints import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.endpoints import AuthOpenApiTags, oauth_router
from app.features.core.auth.endpoints import router as auth_router
from app.features.core.health.endpoints import HealthOpenApiTags
from app.features.core.health.endpoints import router as health_router
from app.infrastructure.oauth import OAuthClients

ERROR_STATUSES = {**AUTH_ERROR_STATUSES}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app.name,
        openapi_tags=[*AuthOpenApiTags.METADATA, *HealthOpenApiTags.METADATA],
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

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return domain_error_response(exc, ERROR_STATUSES)

    return app


app = create_app()
