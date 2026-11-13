import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.features.core.bookings.services.request_expiry_service import RequestExpiryService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.notifications.services.booking_decision_notifier import (
    BookingDecisionNotifier,
)
from app.features.core.notifications.services.decision_email_renderer import (
    DecisionEmailRenderer,
)
from app.features.core.notifications.services.decision_email_service import DecisionEmailService
from app.infrastructure.email import EmailSender

logger = logging.getLogger(__name__)


class RequestExpiryJob:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        settings: Settings,
        email_sender: EmailSender,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._emails = DecisionEmailService(
            email_sender,
            DecisionEmailRenderer(frontend_url=settings.app.frontend_url),
            skip_email_domains=settings.notifications.skip_email_domains,
        )

    async def run(self) -> None:
        async with self._sessionmaker() as session:
            try:
                notices = await self._service(session).reject_expired()
            except BaseException:
                await session.rollback()
                raise
            await session.commit()
        if notices:
            logger.info("Rejected %d pending requests inside the auto-reject lead", len(notices))
        await self._emails.send(notices=notices)

    def _service(self, session: AsyncSession) -> RequestExpiryService:
        return RequestExpiryService(
            session,
            LocationCatalogService(session, public_base_url=self._settings.media.public_base_url),
            BookingDecisionNotifier(session),
            self._settings.booking,
        )
