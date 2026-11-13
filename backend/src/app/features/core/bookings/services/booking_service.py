import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.bookings.dto import BookingView, SlotView
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.features.core.bookings.models import Booking, BookingParticipant
from app.features.core.bookings.repositories import (
    BookableTableRepository,
    BookingParticipantRepository,
    BookingRepository,
)
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.booking_view_builder import BookingViewBuilder
from app.features.core.bookings.services.exceptions import (
    BookingNotFoundError,
    BookingPendingError,
    LargeBookingNotEditableError,
    OverlappingBookingError,
    PartyBelowParticipantsError,
    SlotUnavailableError,
    TableNotFoundError,
    TableNotSuitableError,
)
from app.features.core.bookings.services.inactive_booking_guard import InactiveBookingGuard
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
        self._participants = BookingParticipantRepository(session)
        self._users = UserRepository(session)
        self._schedule = BookingSchedule(settings)
        self._views = BookingViewBuilder(session, locations, self._schedule)
        self._inactive = InactiveBookingGuard()

    async def create(
        self, *, user_id: uuid.UUID, table_id: uuid.UUID, starts_at: datetime, party_size: int
    ) -> BookingView:
        self._schedule.check_requestable_party_size(party_size=party_size)
        start = self._schedule.to_local(starts_at)
        self._schedule.check_date(day=start.date())
        self._schedule.check_slot_time(slot_time=start.time())
        table = await self._tables.get(table_id=table_id)
        if table is None:
            raise TableNotFoundError()
        if not party_size <= table.capacity <= self._schedule.max_capacity(party_size=party_size):
            raise TableNotSuitableError()
        if start <= self._schedule.now():
            raise SlotUnavailableError()
        if self._schedule.initial_status(party_size=party_size) == BookingStatus.PENDING:
            self._schedule.check_requestable_start(starts_at=start, now=clock.now())
        end = start + self._schedule.duration
        # Always the user first, then the table, so two creates never wait on each other crosswise.
        await self._users.get_by_id(user_id=user_id, for_update=True)
        await self._tables.get(table_id=table_id, for_update=True)
        if await self._bookings.table_has_confirmed_overlap(
            table_id=table_id, starts_at=start, ends_at=end
        ):
            raise SlotUnavailableError()
        if await self._bookings.user_has_active_overlap(
            user_id=user_id, starts_at=start, ends_at=end
        ):
            raise OverlappingBookingError()
        booking = Booking(
            user_id=user_id,
            table_id=table_id,
            party_size=party_size,
            starts_at=start,
            ends_at=end,
            status=self._schedule.initial_status(party_size=party_size),
        )
        try:
            await self._bookings.add(booking=booking)
        except IntegrityError as exc:
            if self.EXCLUSION_CONSTRAINT in str(exc.orig):
                raise SlotUnavailableError() from exc
            raise
        owner = BookingParticipant(
            booking_id=booking.id,
            user_id=user_id,
            role=ParticipantRole.OWNER,
            created_at=clock.now(),
        )
        await self._participants.add(participant=owner)
        return await self._views.one(
            booking=booking, table=table, role=ParticipantRole.OWNER, participant_id=owner.id
        )

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[BookingView]:
        return await self._views.many(rows=await self._bookings.list_for_user(user_id=user_id))

    async def cancel(self, *, user_id: uuid.UUID, booking_id: uuid.UUID) -> BookingView:
        row = await self._bookings.get_for_user(
            booking_id=booking_id, user_id=user_id, for_update=True
        )
        if row is None:
            raise BookingNotFoundError()
        booking, table, owner_id = row
        self._inactive.check_active(status=booking.status)
        self._schedule.check_cancellable(starts_at=booking.starts_at)
        booking.status = BookingStatus.CANCELLED
        await self._bookings.flush()
        return await self._views.one(
            booking=booking, table=table, role=ParticipantRole.OWNER, participant_id=owner_id
        )

    async def edit(
        self,
        *,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
        starts_at: datetime,
        party_size: int,
        duration_minutes: int,
    ) -> BookingView:
        booking, table, _ = await self._get_editable(user_id=user_id, booking_id=booking_id)
        self._schedule.check_party_size(party_size=party_size)
        start = self._schedule.to_local(starts_at)
        self._schedule.check_same_day(start=start, current_start=booking.starts_at)
        self._schedule.check_slot_time(slot_time=start.time())
        self._schedule.check_duration(duration_minutes=duration_minutes)
        end = start + timedelta(minutes=duration_minutes)
        self._schedule.check_ends_by_closing(start=start, end=end)
        if party_size > table.capacity:
            raise TableNotSuitableError()
        if start <= self._schedule.now():
            raise SlotUnavailableError()
        await self._users.get_by_id(user_id=user_id, for_update=True)
        await self._tables.get(table_id=table.id, for_update=True)
        booking, table, owner_id = await self._get_editable(
            user_id=user_id, booking_id=booking_id, for_update=True
        )
        if party_size < await self._participants.count(booking_id=booking.id):
            raise PartyBelowParticipantsError()
        if await self._bookings.table_has_confirmed_overlap(
            table_id=table.id, starts_at=start, ends_at=end, excluding_booking_id=booking.id
        ):
            raise SlotUnavailableError()
        if await self._bookings.user_has_active_overlap(
            user_id=user_id, starts_at=start, ends_at=end, excluding_booking_id=booking.id
        ):
            raise OverlappingBookingError()
        booking.starts_at = start
        booking.ends_at = end
        booking.party_size = party_size
        try:
            await self._bookings.flush()
        except IntegrityError as exc:
            if self.EXCLUSION_CONSTRAINT in str(exc.orig):
                raise SlotUnavailableError() from exc
            raise
        return await self._views.one(
            booking=booking, table=table, role=ParticipantRole.OWNER, participant_id=owner_id
        )

    async def list_edit_slots(
        self, *, user_id: uuid.UUID, booking_id: uuid.UUID, duration_minutes: int
    ) -> list[SlotView]:
        booking, table, _ = await self._get_editable(user_id=user_id, booking_id=booking_id)
        self._schedule.check_duration(duration_minutes=duration_minutes)
        duration = timedelta(minutes=duration_minutes)
        starts = self._schedule.starts_on(day=self._schedule.to_local(booking.starts_at).date())
        bookings = await self._bookings.list_confirmed_overlapping(
            table_ids=[table.id],
            starts_at=starts[0],
            ends_at=starts[-1] + duration,
            excluding_booking_id=booking.id,
        )
        now = self._schedule.now()
        return [
            SlotView(
                starts_at=start,
                available=self._schedule.is_free(
                    start=start, duration=duration, bookings=bookings, now=now
                ),
            )
            for start in starts
        ]

    async def _get_editable(
        self, *, user_id: uuid.UUID, booking_id: uuid.UUID, for_update: bool = False
    ) -> tuple[Booking, DiningTable, uuid.UUID]:
        row = await self._bookings.get_for_user(
            booking_id=booking_id, user_id=user_id, for_update=for_update
        )
        if row is None:
            raise BookingNotFoundError()
        booking, table, _ = row
        self._inactive.check_active(status=booking.status)
        if booking.status == BookingStatus.PENDING:
            raise BookingPendingError()
        if self._schedule.is_request_table(capacity=table.capacity):
            raise LargeBookingNotEditableError()
        self._schedule.check_editable(starts_at=booking.starts_at)
        return row
