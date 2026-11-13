from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.auth.endpoints.dependencies import EmailSenderDep
from app.features.core.notifications.services.booking_decision_notifier import (
    BookingDecisionNotifier,
)
from app.features.core.notifications.services.decision_email_renderer import (
    DecisionEmailRenderer,
)
from app.features.core.notifications.services.decision_email_service import DecisionEmailService
from app.features.core.notifications.services.notification_service import NotificationService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_notification_service(session: SessionDep, settings: SettingsDep) -> NotificationService:
    return NotificationService(session, timezone=settings.booking.timezone)


def get_booking_decision_notifier(session: SessionDep) -> BookingDecisionNotifier:
    return BookingDecisionNotifier(session)


def get_decision_email_renderer(settings: SettingsDep) -> DecisionEmailRenderer:
    return DecisionEmailRenderer(frontend_url=settings.app.frontend_url)


DecisionEmailRendererDep = Annotated[DecisionEmailRenderer, Depends(get_decision_email_renderer)]


def get_decision_email_service(
    sender: EmailSenderDep, renderer: DecisionEmailRendererDep, settings: SettingsDep
) -> DecisionEmailService:
    return DecisionEmailService(
        sender, renderer, skip_email_domains=settings.notifications.skip_email_domains
    )


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
BookingDecisionNotifierDep = Annotated[
    BookingDecisionNotifier, Depends(get_booking_decision_notifier)
]
DecisionEmailServiceDep = Annotated[DecisionEmailService, Depends(get_decision_email_service)]
