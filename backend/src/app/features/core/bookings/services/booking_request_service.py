import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.bookings.dto import (
    BookedTableView,
    BookingRequestPage,
    BookingRequestView,
    DecisionOutcome,
)
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.models import Booking
from app.features.core.bookings.repositories import (
    BookableTableRepository,
    BookingParticipantRepository,
    BookingRepository,
)
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.exceptions import (
    BookingNotFoundError,
    RequestExpiredError,
    RequestNotPendingError,
    SlotUnavailableError,
    StaffOnlyError,
)
from app.features.core.locations.dto import LocationView
from app.features.core.locations.models import DiningTable
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.notifications.dto import DecisionNotice, NoticeRecipient
from app.features.core.notifications.enums import NotificationKind
from app.features.core.notifications.services.booking_decision_notifier import (
    BookingDecisionNotifier,
)
from app.features.core.users.repositories import UserRepository


class BookingRequestService:
    EXCLUSION_CONSTRAINT = "ex_bookings_table_id_period"

    def __init__(
        self,
        session: AsyncSession,
        locations: LocationCatalogService,
        notifier: BookingDecisionNotifier,
        settings: BookingSettings,
    ) -> None:
        self._bookings = BookingRepository(session)
        self._tables = BookableTableRepository(session)
        self._participants = BookingParticipantRepository(session)
        self._users = UserRepository(session)
        self._locations = locations
        self._notifier = notifier
        self._schedule = BookingSchedule(settings)

    async def list_pending(
        self, *, staff_id: uuid.UUID, limit: int, offset: int
    ) -> BookingRequestPage:
        await self._check_staff(user_id=staff_id)
        now = clock.now()
        rows = await self._bookings.list_pending_requests(
            starting_after=now, limit=limit, offset=offset
        )
        locations = {location.id: location for location in await self._locations.list_all()}
        return BookingRequestPage(
            items=[
                self._to_view(booking, table, locations[table.location_id], name, competing)
                for booking, table, name, competing in rows
            ],
            total=await self._bookings.count_pending_requests(starting_after=now),
            limit=limit,
            offset=offset,
        )

    async def approve(self, *, staff_id: uuid.UUID, booking_id: uuid.UUID) -> DecisionOutcome:
        await self._check_staff(user_id=staff_id)
        booking, table = await self._get(booking_id=booking_id)
        competitor_ids = await self._bookings.list_pending_overlapping_ids(
            table_id=table.id,
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
            excluding_booking_id=booking.id,
        )
        # Users, then the table, then the request: the lock order of ADR 13. The recipients' user
        # rows are key-share locked up front, because the notification inserts need them.
        await self._participants.lock_account_holders(booking_ids=[booking.id, *competitor_ids])
        await self._tables.get(table_id=table.id, for_update=True)
        booking, table = await self._get(booking_id=booking_id, for_update=True)
        self._check_pending(booking)
        now = clock.now()
        if booking.starts_at <= now:
            raise RequestExpiredError()
        if await self._bookings.table_has_confirmed_overlap(
            table_id=table.id, starts_at=booking.starts_at, ends_at=booking.ends_at
        ):
            raise SlotUnavailableError()
        self._decide(booking, status=BookingStatus.CONFIRMED, staff_id=staff_id, now=now)
        try:
            await self._bookings.flush()
        except IntegrityError as exc:
            if self.EXCLUSION_CONSTRAINT in str(exc.orig):
                raise SlotUnavailableError() from exc
            raise
        rejected_ids = await self._bookings.reject_pending_overlapping(
            table_id=table.id,
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
            excluding_booking_id=booking.id,
            decided_at=now,
            decided_by_id=staff_id,
        )
        notices = [
            *await self._notices(
                kind=NotificationKind.BOOKING_REQUEST_APPROVED, booking_ids=[booking.id]
            ),
            *await self._notices(
                kind=NotificationKind.BOOKING_REQUEST_REJECTED, booking_ids=rejected_ids
            ),
        ]
        return await self._outcome(booking_id=booking.id, notices=notices, decided_at=now)

    async def reject(self, *, staff_id: uuid.UUID, booking_id: uuid.UUID) -> DecisionOutcome:
        await self._check_staff(user_id=staff_id)
        await self._participants.lock_account_holders(booking_ids=[booking_id])
        booking, _ = await self._get(booking_id=booking_id, for_update=True)
        self._check_pending(booking)
        now = clock.now()
        self._decide(booking, status=BookingStatus.REJECTED, staff_id=staff_id, now=now)
        await self._bookings.flush()
        notices = await self._notices(
            kind=NotificationKind.BOOKING_REQUEST_REJECTED, booking_ids=[booking.id]
        )
        return await self._outcome(booking_id=booking.id, notices=notices, decided_at=now)

    async def _check_staff(self, *, user_id: uuid.UUID) -> None:
        user = await self._users.get_by_id(user_id=user_id)
        if user is None or not user.is_staff:
            raise StaffOnlyError()

    async def _get(
        self, *, booking_id: uuid.UUID, for_update: bool = False
    ) -> tuple[Booking, DiningTable]:
        row = await self._bookings.get(booking_id=booking_id, for_update=for_update)
        if row is None:
            raise BookingNotFoundError()
        return row

    def _check_pending(self, booking: Booking) -> None:
        if booking.status != BookingStatus.PENDING:
            raise RequestNotPendingError()

    def _decide(
        self, booking: Booking, *, status: BookingStatus, staff_id: uuid.UUID, now: datetime
    ) -> None:
        booking.status = status
        booking.decided_at = now
        booking.decided_by_id = staff_id

    async def _outcome(
        self, *, booking_id: uuid.UUID, notices: list[DecisionNotice], decided_at: datetime
    ) -> DecisionOutcome:
        await self._notifier.record(notices=notices, created_at=decided_at)
        return DecisionOutcome(view=await self._view(booking_id=booking_id), notices=notices)

    async def _notices(
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

    async def _view(self, *, booking_id: uuid.UUID) -> BookingRequestView:
        row = await self._bookings.get_request(booking_id=booking_id)
        if row is None:
            raise BookingNotFoundError()
        booking, table, name, competing = row
        location = await self._locations.get(location_id=table.location_id)
        return self._to_view(booking, table, location, name, competing)

    def _to_view(
        self,
        booking: Booking,
        table: DiningTable,
        location: LocationView,
        owner_first_name: str,
        competing_requests: int,
    ) -> BookingRequestView:
        return BookingRequestView(
            id=booking.id,
            status=booking.status,
            owner_first_name=owner_first_name,
            party_size=booking.party_size,
            starts_at=self._schedule.to_local(booking.starts_at),
            ends_at=self._schedule.to_local(booking.ends_at),
            created_at=self._schedule.to_local(booking.created_at),
            table=BookedTableView(id=table.id, label=table.label, capacity=table.capacity),
            location=location,
            competing_requests=competing_requests,
        )
