import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import BookingSettings
from app.features.core.bookings.dto import BookedTableView, BookingView
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.models import Booking
from app.features.core.bookings.repositories import BookableTableRepository, BookingRepository
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingNotFoundError,
    OverlappingBookingError,
    SlotUnavailableError,
    TableNotFoundError,
    TableNotSuitableError,
)
from app.features.core.locations.dto import LocationView
from app.features.core.locations.models import DiningTable
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.users.repositories import UserRepository


class BookingService:
    EXCLUSION_CONSTRAINT = "ex_bookings_table_id_period"

    def __init__(
        self, session: AsyncSession, locations: LocationCatalogService, settings: BookingSettings
    ) -> None:
        self._bookings = BookingRepository(session)
        self._tables = BookableTableRepository(session)
        self._users = UserRepository(session)
        self._locations = locations
        self._schedule = BookingSchedule(settings)

    async def create(
        self, *, user_id: uuid.UUID, table_id: uuid.UUID, starts_at: datetime, party_size: int
    ) -> BookingView:
        self._schedule.check_party_size(party_size=party_size)
        start = self._schedule.to_local(starts_at)
        self._schedule.check_date(day=start.date())
        self._schedule.check_slot_time(slot_time=start.time())
        table = await self._tables.get(table_id=table_id)
        if table is None:
            raise TableNotFoundError()
        if not party_size <= table.capacity <= self._schedule.max_party_size:
            raise TableNotSuitableError()
        if start <= self._schedule.now():
            raise SlotUnavailableError()
        end = start + self._schedule.duration
        # Always the user first, then the table, so two creates never wait on each other crosswise.
        await self._users.get_by_id(user_id=user_id, for_update=True)
        await self._tables.get(table_id=table_id, for_update=True)
        if await self._bookings.table_has_confirmed_overlap(
            table_id=table_id, starts_at=start, ends_at=end
        ):
            raise SlotUnavailableError()
        if await self._bookings.user_has_confirmed_overlap(
            user_id=user_id, starts_at=start, ends_at=end
        ):
            raise OverlappingBookingError()
        booking = Booking(
            user_id=user_id,
            table_id=table_id,
            party_size=party_size,
            starts_at=start,
            ends_at=end,
            status=BookingStatus.CONFIRMED,
        )
        try:
            await self._bookings.add(booking=booking)
        except IntegrityError as exc:
            if self.EXCLUSION_CONSTRAINT in str(exc.orig):
                raise SlotUnavailableError() from exc
            raise
        location = await self._locations.get(location_id=table.location_id)
        return self._to_view(booking, table, location)

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[BookingView]:
        rows = await self._bookings.list_for_user(user_id=user_id)
        locations = {location.id: location for location in await self._locations.list_all()}
        return [
            self._to_view(booking, table, locations[table.location_id]) for booking, table in rows
        ]

    async def cancel(self, *, user_id: uuid.UUID, booking_id: uuid.UUID) -> BookingView:
        row = await self._bookings.get_for_user(
            booking_id=booking_id, user_id=user_id, for_update=True
        )
        if row is None:
            raise BookingNotFoundError()
        booking, table = row
        if booking.status == BookingStatus.CANCELLED:
            raise BookingAlreadyCancelledError()
        self._schedule.check_cancellable(starts_at=booking.starts_at)
        booking.status = BookingStatus.CANCELLED
        await self._bookings.flush()
        location = await self._locations.get(location_id=table.location_id)
        return self._to_view(booking, table, location)

    def _to_view(self, booking: Booking, table: DiningTable, location: LocationView) -> BookingView:
        return BookingView(
            id=booking.id,
            status=booking.status,
            party_size=booking.party_size,
            starts_at=self._schedule.to_local(booking.starts_at),
            ends_at=self._schedule.to_local(booking.ends_at),
            table=BookedTableView(id=table.id, label=table.label, capacity=table.capacity),
            location=location,
        )
