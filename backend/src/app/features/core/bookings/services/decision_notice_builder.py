import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import BookingSettings
from app.features.core.bookings.repositories import (
    BookingParticipantRepository,
    BookingRepository,
)
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.notifications.dto import DecisionNotice, NoticeRecipient
from app.features.core.notifications.enums import NotificationKind


class DecisionNoticeBuilder:
    def __init__(
        self, session: AsyncSession, locations: LocationCatalogService, settings: BookingSettings
    ) -> None:
        self._bookings = BookingRepository(session)
        self._participants = BookingParticipantRepository(session)
        self._locations = locations
        self._schedule = BookingSchedule(settings)

    async def build(
        self, *, kind: NotificationKind, booking_ids: Sequence[uuid.UUID]
    ) -> list[DecisionNotice]:
        recipients: dict[uuid.UUID, list[NoticeRecipient]] = {}
        for booking_id, user in await self._participants.list_account_holders(
            booking_ids=booking_ids
        ):
            recipients.setdefault(booking_id, []).append(
                NoticeRecipient(user_id=user.id, email=user.email, first_name=user.first_name)
            )
        notices = []
        for booking, table in await self._bookings.list_with_tables(booking_ids=booking_ids):
            location = await self._locations.get(location_id=table.location_id)
            notices.append(
                DecisionNotice(
                    kind=kind,
                    booking_id=booking.id,
                    starts_at=self._schedule.to_local(booking.starts_at),
                    location_address=location.address,
                    party_size=booking.party_size,
                    recipients=recipients.get(booking.id, []),
                )
            )
        return notices
