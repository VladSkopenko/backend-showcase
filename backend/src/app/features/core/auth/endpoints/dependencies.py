from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.auth.services.email_verification_service import EmailVerificationService
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.registration_service import RegistrationService
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.auth.services.verification_email_renderer import (
    VerificationEmailRenderer,
)
from app.features.core.auth.services.verification_email_service import VerificationEmailService
from app.infrastructure.email import EmailSender, LoggingEmailSender, SmtpEmailSender

# scope="function": the commit finishes before the response is sent and the background email runs.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_email_sender(settings: SettingsDep) -> EmailSender:
    if settings.email.is_configured:
        return SmtpEmailSender(settings.email)
    return LoggingEmailSender(settings.app.environment)


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


def get_registration_service(
    session: SessionDep,
    password_hasher: PasswordHasherDep,
    code_service: VerificationCodeServiceDep,
) -> RegistrationService:
    return RegistrationService(session, password_hasher, code_service)


def get_email_verification_service(
    session: SessionDep, code_service: VerificationCodeServiceDep
) -> EmailVerificationService:
    return EmailVerificationService(session, code_service)


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
