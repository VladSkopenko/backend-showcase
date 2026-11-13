from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.auth.endpoints.cookies import SessionCookies
from app.features.core.auth.endpoints.oauth_redirects import OAuthRedirects
from app.features.core.auth.enums import OAuthProvider
from app.features.core.auth.schemas import UserResponse
from app.features.core.auth.services.access_token_codec import AccessTokenCodec
from app.features.core.auth.services.current_user_service import CurrentUserService
from app.features.core.auth.services.email_verification_service import EmailVerificationService
from app.features.core.auth.services.login_service import LoginService
from app.features.core.auth.services.oauth_providers import OAuthProviderRegistry
from app.features.core.auth.services.oauth_sign_in_service import OAuthSignInService
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.password_reset_service import PasswordResetService
from app.features.core.auth.services.registration_service import RegistrationService
from app.features.core.auth.services.session_service import SessionService
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.auth.services.verification_email_renderer import (
    VerificationEmailRenderer,
)
from app.features.core.auth.services.verification_email_service import VerificationEmailService
from app.infrastructure.email import EmailSender, create_email_sender
from app.infrastructure.oauth import OAuthClients

# scope="function": the commit finishes before the response is sent and the background email runs.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_email_sender(settings: SettingsDep) -> EmailSender:
    return create_email_sender(settings=settings.email, environment=settings.app.environment)


@lru_cache
def get_password_hasher() -> PasswordHasher:
    return PasswordHasher()


def get_verification_email_renderer(settings: SettingsDep) -> VerificationEmailRenderer:
    return VerificationEmailRenderer(
        frontend_url=settings.app.frontend_url,
        ttl_minutes=settings.auth.verification_code_ttl_minutes,
    )


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
PasswordHasherDep = Annotated[PasswordHasher, Depends(get_password_hasher)]
EmailRendererDep = Annotated[VerificationEmailRenderer, Depends(get_verification_email_renderer)]


def get_verification_code_service(
    session: SessionDep, settings: SettingsDep
) -> VerificationCodeService:
    return VerificationCodeService(session, settings.auth, settings.app.environment)


VerificationCodeServiceDep = Annotated[
    VerificationCodeService, Depends(get_verification_code_service)
]


def get_access_token_codec(settings: SettingsDep) -> AccessTokenCodec:
    return AccessTokenCodec(
        secret_key=settings.token.secret_key.get_secret_value(),
        algorithm=settings.token.algorithm,
        ttl_minutes=settings.token.access_ttl_minutes,
    )


AccessTokenCodecDep = Annotated[AccessTokenCodec, Depends(get_access_token_codec)]


def get_session_service(
    session: SessionDep, codec: AccessTokenCodecDep, settings: SettingsDep
) -> SessionService:
    return SessionService(session, codec, refresh_ttl_days=settings.token.refresh_ttl_days)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


def get_registration_service(
    session: SessionDep,
    password_hasher: PasswordHasherDep,
    code_service: VerificationCodeServiceDep,
) -> RegistrationService:
    return RegistrationService(session, password_hasher, code_service)


def get_email_verification_service(
    session: SessionDep,
    code_service: VerificationCodeServiceDep,
    session_service: SessionServiceDep,
) -> EmailVerificationService:
    return EmailVerificationService(session, code_service, session_service)


def get_login_service(
    session: SessionDep,
    password_hasher: PasswordHasherDep,
    session_service: SessionServiceDep,
    settings: SettingsDep,
) -> LoginService:
    return LoginService(session, password_hasher, session_service, settings.auth)


def get_password_reset_service(
    session: SessionDep,
    password_hasher: PasswordHasherDep,
    code_service: VerificationCodeServiceDep,
    session_service: SessionServiceDep,
) -> PasswordResetService:
    return PasswordResetService(session, password_hasher, code_service, session_service)


def get_current_user_service(session: SessionDep, codec: AccessTokenCodecDep) -> CurrentUserService:
    return CurrentUserService(session, codec)


def get_session_cookies(request: Request, settings: SettingsDep) -> SessionCookies:
    return SessionCookies(settings.token, request.cookies)


def get_verification_email_service(
    sender: EmailSenderDep, renderer: EmailRendererDep
) -> VerificationEmailService:
    return VerificationEmailService(sender, renderer)


RegistrationServiceDep = Annotated[RegistrationService, Depends(get_registration_service)]
EmailVerificationServiceDep = Annotated[
    EmailVerificationService, Depends(get_email_verification_service)
]
VerificationEmailServiceDep = Annotated[
    VerificationEmailService, Depends(get_verification_email_service)
]
LoginServiceDep = Annotated[LoginService, Depends(get_login_service)]
PasswordResetServiceDep = Annotated[PasswordResetService, Depends(get_password_reset_service)]
CurrentUserServiceDep = Annotated[CurrentUserService, Depends(get_current_user_service)]
SessionCookiesDep = Annotated[SessionCookies, Depends(get_session_cookies)]

OAUTH_PROVIDERS_BY_SLUG = {provider.slug: provider for provider in OAuthProvider}


# The path carries the lowercase slug. An enum parameter would accept only "GOOGLE" and answer
# 422, so the known slugs are only documented and an unknown one stays a 404.
def get_oauth_provider(
    provider_slug: Annotated[
        str,
        Path(json_schema_extra={"enum": list(OAUTH_PROVIDERS_BY_SLUG)}),
    ],
) -> OAuthProvider:
    provider = OAUTH_PROVIDERS_BY_SLUG.get(provider_slug)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return provider


# Built once in create_app: authlib caches provider metadata and keys on the client instance.
def get_oauth_clients(request: Request) -> OAuthClients:
    clients: OAuthClients = request.app.state.oauth_clients
    return clients


def get_oauth_provider_registry(settings: SettingsDep) -> OAuthProviderRegistry:
    return OAuthProviderRegistry(google=settings.google)


def get_oauth_redirects(settings: SettingsDep) -> OAuthRedirects:
    return OAuthRedirects(frontend_url=settings.app.frontend_url)


OAuthProviderRegistryDep = Annotated[OAuthProviderRegistry, Depends(get_oauth_provider_registry)]


def get_oauth_sign_in_service(
    session: SessionDep, registry: OAuthProviderRegistryDep, session_service: SessionServiceDep
) -> OAuthSignInService:
    return OAuthSignInService(session, registry, session_service)


OAuthProviderDep = Annotated[OAuthProvider, Depends(get_oauth_provider)]
OAuthClientsDep = Annotated[OAuthClients, Depends(get_oauth_clients)]
OAuthRedirectsDep = Annotated[OAuthRedirects, Depends(get_oauth_redirects)]
OAuthSignInServiceDep = Annotated[OAuthSignInService, Depends(get_oauth_sign_in_service)]


# Typed as the response schema: endpoints may not import the User model (ADR 11).
async def get_current_user(
    current_user: CurrentUserServiceDep,
    access_token: Annotated[str | None, Cookie(alias=SessionCookies.ACCESS_NAME)] = None,
) -> UserResponse:
    return UserResponse.model_validate(await current_user.get(access_token=access_token))


CurrentUserDep = Annotated[UserResponse, Depends(get_current_user)]


async def get_optional_user(
    current_user: CurrentUserServiceDep,
    access_token: Annotated[str | None, Cookie(alias=SessionCookies.ACCESS_NAME)] = None,
) -> UserResponse | None:
    if access_token is None:
        return None
    return UserResponse.model_validate(await current_user.get(access_token=access_token))


OptionalUserDep = Annotated[UserResponse | None, Depends(get_optional_user)]
