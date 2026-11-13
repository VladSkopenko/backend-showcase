from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.bookings.repositories import (
    BookingParticipantRepository,
    BookingRepository,
)
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.decision_notice_builder import DecisionNoticeBuilder
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.notifications.dto import DecisionNotice
from app.features.core.notifications.enums import NotificationKind
from app.features.core.notifications.services.booking_decision_notifier import (
    BookingDecisionNotifier,
)


class RequestExpiryService:
    def __init__(
        self,
        session: AsyncSession,
        locations: LocationCatalogService,
        notifier: BookingDecisionNotifier,
        settings: BookingSettings,
    ) -> None:
        self._bookings = BookingRepository(session)
        self._participants = BookingParticipantRepository(session)
        self._notices = DecisionNoticeBuilder(session, locations, settings)
        self._notifier = notifier
        self._schedule = BookingSchedule(settings)

    async def reject_expired(self) -> list[DecisionNotice]:
        now = clock.now()
        starts_by = self._schedule.auto_reject_starts_by(now=now)
        expiring_ids = await self._bookings.list_pending_starting_by(starts_by=starts_by)
        if not expiring_ids:
            return []
        # Users before bookings (ADR 13): the notification inserts key-share lock the recipients.
        await self._participants.lock_account_holders(booking_ids=expiring_ids)
        rejected_ids = await self._bookings.reject_pending_starting_by(
            booking_ids=expiring_ids, starts_by=starts_by, decided_at=now
        )
        notices = await self._notices.build(
            kind=NotificationKind.BOOKING_REQUEST_REJECTED, booking_ids=rejected_ids
        )
        await self._notifier.record(notices=notices, created_at=now)
        return notices
