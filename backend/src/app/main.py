from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.common.database import get_engine, get_sessionmaker
from app.common.error_responses import (
    domain_error_response,
    http_error_response,
    server_error_response,
    validation_error_response,
)
from app.common.errors import DomainError
from app.config.settings import Settings, get_settings
from app.config.log_setup import configure_logging
from app.features.assistant.endpoints import ERROR_STATUSES as ASSISTANT_ERROR_STATUSES
from app.features.assistant.endpoints import AssistantOpenApiTags
from app.features.assistant.endpoints import router as assistant_router
from app.features.assistant.endpoints.dependencies import build_chat_model
from app.features.core.auth.endpoints import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.endpoints import AuthOpenApiTags, oauth_router
from app.features.core.auth.endpoints import router as auth_router
from app.features.core.bookings.endpoints import ERROR_STATUSES as BOOKINGS_ERROR_STATUSES
from app.features.core.bookings.endpoints import BookingOpenApiTags, staff_router
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
from app.infrastructure.background_tasks import CleanupJob, PeriodicTask, RequestExpiryJob
from app.infrastructure.email import create_email_sender
from app.infrastructure.metrics import MetricsServer, RequestMetricsMiddleware, RouteTemplates
from app.infrastructure.oauth import OAuthClients

ERROR_STATUSES = {
    **AUTH_ERROR_STATUSES,
    **MENU_ERROR_STATUSES,
    **LOCATIONS_ERROR_STATUSES,
    **BOOKINGS_ERROR_STATUSES,
    **INVITES_ERROR_STATUSES,
    **PREORDER_ERROR_STATUSES,
    **ASSISTANT_ERROR_STATUSES,
}

ROUTERS: list[tuple[APIRouter, str]] = [
    (health_router, ""),
    (auth_router, "/api/v1"),
    (oauth_router, "/api/v1"),
    (menu_router, "/api/v1"),
    (locations_router, "/api/v1"),
    (bookings_router, "/api/v1"),
    (invites_router, "/api/v1"),
    (preorder_router, "/api/v1"),
    (assistant_router, "/api/v1"),
    (staff_router, "/api/v1"),
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    metrics_server = MetricsServer(port=settings.metrics.port, registry=app.state.metrics_registry)
    metrics_server.start()
    app.state.metrics_server = metrics_server
    try:
        request_expiry = PeriodicTask(
            name="request expiry",
            interval_seconds=settings.booking.auto_reject_interval_seconds,
            job=RequestExpiryJob(
                get_sessionmaker(),
                settings=settings,
                email_sender=create_email_sender(
                    settings=settings.email, environment=settings.app.environment
                ),
            ).run,
        )
        cleanup = PeriodicTask(
            name="cleanup",
            interval_seconds=settings.cleanup.interval_seconds,
            job=CleanupJob(
                get_sessionmaker(),
                assistant_session_ttl_days=settings.assistant.session_ttl_days,
            ).run,
        )
        request_expiry.start()
        cleanup.start()
        try:
            yield
        finally:
            await cleanup.stop()
            await request_expiry.stop()
            await get_engine().dispose()
    finally:
        metrics_server.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.app.log_level)
    app = FastAPI(
        title="backend-showcase",
        lifespan=lifespan,
        openapi_tags=[
            *AuthOpenApiTags.METADATA,
            *MenuOpenApiTags.METADATA,
            *LocationsOpenApiTags.METADATA,
            *BookingOpenApiTags.METADATA,
            *InvitesOpenApiTags.METADATA,
            *PreorderOpenApiTags.METADATA,
            *AssistantOpenApiTags.METADATA,
            *BookingOpenApiTags.STAFF_METADATA,
            *HealthOpenApiTags.METADATA,
        ],
    )
    app.state.settings = settings
    app.state.chat_model = build_chat_model(settings.openai)
    app.state.oauth_clients = OAuthClients(google=settings.google)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.token.secret_key.get_secret_value(),
        session_cookie="oauth_state",
        max_age=settings.auth.oauth_state_max_age_seconds,
        path=settings.auth.oauth_state_cookie_path,
        same_site="lax",
        https_only=True,
    )
    app.state.metrics_registry = CollectorRegistry()
    app.add_middleware(
        RequestMetricsMiddleware,
        registry=app.state.metrics_registry,
        route_templates=RouteTemplates(ROUTERS),
    )
    for router, prefix in ROUTERS:
        app.include_router(router, prefix=prefix)

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

    @app.exception_handler(Exception)
    async def handle_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        return server_error_response()

    return app
