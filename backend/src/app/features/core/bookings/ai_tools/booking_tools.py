import datetime
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.ai_tools import (
    ActionApplier,
    AiToolContext,
    AiToolErrors,
    Card,
    CardField,
    dry_run,
    invalid_arguments,
    tool_error,
    tool_result,
)
from app.features.core.bookings.ai_tools.arguments import (
    CancelBookingArguments,
    CreateBookingArguments,
    EditBookingArguments,
    FindTablesArguments,
    ListMyBookingsArguments,
)
from app.features.core.bookings.ai_tools.booking_cancel_applier import BookingCancelApplier
from app.features.core.bookings.ai_tools.booking_create_applier import BookingCreateApplier
from app.features.core.bookings.ai_tools.booking_edit_applier import BookingEditApplier
from app.features.core.bookings.dto import BookingView, SlotView, TableCardView
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.bookings.services.table_search_service import TableSearchService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingTools:
    SEARCH_LIMIT = 50
    UPCOMING_BOOKINGS_LIMIT = 10
    PAST_BOOKINGS_LIMIT = 10

    def __init__(self, context: AiToolContext) -> None:
        self._context = context
        self._schedule = BookingSchedule(context.booking)

    def build(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                coroutine=self._find_tables,
                name="find_tables",
                description=(
                    "Finds the tables that fit a party on a day, grouped by location (id and "
                    "address). Each table says whether it is booked by a request the staff "
                    "confirm (`by_request`) and lists its free "
                    "starts that day as `free_start_ranges`: runs of consecutive free starts on "
                    'the slot grid written as "HH:MM-HH:MM" (the first and the last free start '
                    "of the run, restaurant time). With `time`, only tables free at that start "
                    "are listed. Few free starts across the tables mean a busy day or evening. "
                    f"At most {self.SEARCH_LIMIT} tables are listed; `total` counts every table "
                    "that matches."
                ),
                args_schema=FindTablesArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._list_my_bookings,
                name="list_my_bookings",
                description=(
                    "Lists the guest's own bookings and the ones the guest joined: first the "
                    f"{self.UPCOMING_BOOKINGS_LIMIT} soonest bookings not yet over, in any status, "
                    f"then the latest {self.PAST_BOOKINGS_LIMIT} past ones. Each has its status, "
                    "start and end in restaurant time, party size, table, location address, the "
                    "guest's role and the participants."
                ),
                args_schema=ListMyBookingsArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._create_booking,
                name="create_booking",
                description=(
                    "Proposes booking a table for the guest: checks every booking rule and, when "
                    "the booking is possible, shows the guest a card to confirm. Nothing is "
                    "booked until the guest applies the card. An error names the rule that "
                    "refused it, so another table or time can be tried. One proposal per answer."
                ),
                args_schema=CreateBookingArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._edit_booking,
                name="edit_booking",
                description=(
                    "Proposes changing one of the guest's own bookings: a new start on the same "
                    "day, party size or length of the visit; omitted values stay as they are. "
                    "Checks every rule and, when the change is possible, shows the guest a card "
                    "to confirm. Nothing changes until the guest applies the card. An error "
                    "names the rule that refused it; NOTHING_TO_CHANGE means the request "
                    "changes nothing in the booking. One proposal per answer."
                ),
                args_schema=EditBookingArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._cancel_booking,
                name="cancel_booking",
                description=(
                    "Proposes cancelling one of the guest's own bookings or booking requests: "
                    "checks the rules and, when it is possible, shows the guest a card to "
                    "confirm. Nothing is cancelled until the guest applies the card. One "
                    "proposal per answer."
                ),
                args_schema=CancelBookingArguments,
                handle_validation_error=invalid_arguments,
            ),
        ]

    def appliers(self) -> dict[str, ActionApplier]:
        return {
            BookingCreateApplier.KIND: BookingCreateApplier(self._context),
            BookingEditApplier.KIND: BookingEditApplier(self._context),
            BookingCancelApplier.KIND: BookingCancelApplier(self._context),
        }

    async def _find_tables(
        self,
        date: datetime.date,
        party_size: int,
        location_id: uuid.UUID | None = None,
        time: datetime.time | None = None,
    ) -> str:
        async with self._context.sessionmaker() as session:
            page = await TableSearchService(
                session, self._locations(session), self._context.booking
            ).search(
                day=date,
                party_size=party_size,
                location_id=location_id,
                slot_time=time,
                limit=self.SEARCH_LIMIT,
                offset=0,
            )
        locations: dict[uuid.UUID, dict[str, Any]] = {}
        for card in page.items:
            location = locations.setdefault(
                card.location.id,
                {"id": str(card.location.id), "address": card.location.address, "tables": []},
            )
            location["tables"].append(self._table(card))
        return tool_result({"total": page.total, "locations": list(locations.values())})

    async def _list_my_bookings(self) -> str:
        async with self._context.sessionmaker() as session:
            bookings = await BookingService(
                session, self._locations(session), self._context.booking
            ).list_for_user(user_id=self._context.user_id)
        now = clock.now()
        upcoming = [booking for booking in reversed(bookings) if booking.ends_at > now]
        past = [booking for booking in bookings if booking.ends_at <= now]
        shown = [
            *upcoming[: self.UPCOMING_BOOKINGS_LIMIT],
            *past[: self.PAST_BOOKINGS_LIMIT],
        ]
        return tool_result([self._booking(booking) for booking in shown])

    async def _create_booking(
        self, table_id: uuid.UUID, date: datetime.date, time: datetime.time, party_size: int
    ) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        starts_at = self._schedule.start_at(day=date, slot_time=time)
        async with dry_run(self._context.sessionmaker) as session:
            booking = await BookingService(
                session, self._locations(session), self._context.booking
            ).create(
                user_id=self._context.user_id,
                table_id=table_id,
                starts_at=starts_at,
                party_size=party_size,
            )
        card = self._booking_card(booking)
        return proposals.propose(
            kind=BookingCreateApplier.KIND,
            payload={
                "table_id": str(table_id),
                "starts_at": starts_at.isoformat(),
                "party_size": party_size,
            },
            card=card,
        )

    async def _edit_booking(
        self,
        booking_id: uuid.UUID,
        time: datetime.time | None = None,
        party_size: int | None = None,
        duration_minutes: int | None = None,
    ) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        async with dry_run(self._context.sessionmaker) as session:
            locations = self._locations(session)
            current = await ParticipantService(
                session, locations, self._context.booking
            ).get_for_participant(
                booking_id=booking_id, user_id=self._context.user_id, guest_token=None
            )
            current_start = self._schedule.to_local(current.starts_at)
            current_duration = self._duration_minutes(current)
            starts_at = self._schedule.start_at(
                day=current_start.date(),
                slot_time=current_start.time() if time is None else time,
            )
            new_party_size = current.party_size if party_size is None else party_size
            new_duration = current_duration if duration_minutes is None else duration_minutes
            if (starts_at, new_party_size, new_duration) == (
                current_start,
                current.party_size,
                current_duration,
            ):
                return tool_error(AiToolErrors.NOTHING_TO_CHANGE)
            edited = await BookingService(session, locations, self._context.booking).edit(
                user_id=self._context.user_id,
                booking_id=booking_id,
                starts_at=starts_at,
                party_size=new_party_size,
                duration_minutes=new_duration,
            )
        before = f"{self._period(current)}, {current.party_size} guests"
        card = Card(
            title="Change the booking",
            fields=[*self._booking_fields(edited), CardField(label="Before", value=before)],
            notice=None,
            confirm_label="Change",
        )
        return proposals.propose(
            kind=BookingEditApplier.KIND,
            payload={
                "booking_id": str(booking_id),
                "starts_at": starts_at.isoformat(),
                "party_size": new_party_size,
                "duration_minutes": new_duration,
                "before": {
                    "starts_at": current_start.isoformat(),
                    "party_size": current.party_size,
                    "duration_minutes": current_duration,
                },
            },
            card=card,
        )

    async def _cancel_booking(self, booking_id: uuid.UUID) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        async with dry_run(self._context.sessionmaker) as session:
            cancelled = await BookingService(
                session, self._locations(session), self._context.booking
            ).cancel(user_id=self._context.user_id, booking_id=booking_id)
        card = Card(
            title="Cancel the booking",
            fields=self._booking_fields(cancelled),
            notice="This cannot be undone.",
            confirm_label="Yes, cancel it",
        )
        return proposals.propose(
            kind=BookingCancelApplier.KIND,
            payload={"booking_id": str(booking_id)},
            card=card,
        )

    def _booking_card(self, booking: BookingView) -> Card:
        notice = (
            "Sent as a request; the restaurant confirms it."
            if booking.status == BookingStatus.PENDING
            else None
        )
        return Card(
            title="Book a table",
            fields=self._booking_fields(booking),
            notice=notice,
            confirm_label="Book",
        )

    def _booking_fields(self, booking: BookingView) -> list[CardField]:
        start = self._schedule.to_local(booking.starts_at)
        return [
            CardField(label="Location", value=booking.location.address),
            CardField(
                label="Table",
                value=f"{booking.table.label}, up to {booking.table.capacity} guests",
            ),
            CardField(label="Date", value=f"{start:%a, %d %b %Y}"),
            CardField(label="Time", value=self._period(booking)),
            CardField(label="Guests", value=str(booking.party_size)),
        ]

    def _period(self, booking: BookingView) -> str:
        start = self._schedule.to_local(booking.starts_at)
        end = self._schedule.to_local(booking.ends_at)
        return f"{start:%H:%M} – {end:%H:%M}"

    @staticmethod
    def _duration_minutes(booking: BookingView) -> int:
        return (booking.ends_at - booking.starts_at) // datetime.timedelta(minutes=1)

    def _locations(self, session: AsyncSession) -> LocationCatalogService:
        return LocationCatalogService(session, public_base_url=self._context.public_base_url)

    def _table(self, card: TableCardView) -> dict[str, Any]:
        return {
            "id": str(card.id),
            "label": card.label,
            "capacity": card.capacity,
            "by_request": self._schedule.is_request_table(capacity=card.capacity),
            "free_start_ranges": self._free_start_ranges(card.slots),
        }

    @staticmethod
    def _free_start_ranges(slots: list[SlotView]) -> list[str]:
        runs: list[list[SlotView]] = []
        previous_free = False
        for slot in slots:
            if slot.available:
                if previous_free:
                    runs[-1].append(slot)
                else:
                    runs.append([slot])
            previous_free = slot.available
        return [f"{run[0].starts_at:%H:%M}-{run[-1].starts_at:%H:%M}" for run in runs]

    @staticmethod
    def _booking(booking: BookingView) -> dict[str, Any]:
        return {
            "id": str(booking.id),
            "status": booking.status.value,
            "starts_at": booking.starts_at.isoformat(),
            "ends_at": booking.ends_at.isoformat(),
            "party_size": booking.party_size,
            "table": {"label": booking.table.label, "capacity": booking.table.capacity},
            "location": {"address": booking.location.address},
            "role": booking.role.value,
            "participants": [
                {"name": participant.name, "role": participant.role.value}
                for participant in booking.participants
            ],
        }
