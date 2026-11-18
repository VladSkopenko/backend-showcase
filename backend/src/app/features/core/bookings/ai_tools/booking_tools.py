import dataclasses
import datetime
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.ai_tools import (
    ActionApplier,
    ActionContext,
    AiToolContext,
    AiToolErrors,
    Card,
    CardField,
    Proposal,
    dry_run,
    invalid_arguments,
    tool_error,
    tool_result,
)
from app.features.core.bookings.ai_tools.arguments import (
    CreateBookingArguments,
    FindTablesArguments,
    ListMyBookingsArguments,
)
from app.features.core.bookings.dto import BookingView, SlotView, TableCardView
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.bookings.services.table_search_service import TableSearchService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingCreateApplier:
    """Applies a confirmed `booking.create` card through the route's own service."""

    KIND = "booking.create"

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        locations = LocationCatalogService(
            context.session, public_base_url=self._context.public_base_url
        )
        booking = await BookingService(context.session, locations, self._context.booking).create(
            user_id=context.user_id,
            table_id=uuid.UUID(context.payload["table_id"]),
            starts_at=datetime.datetime.fromisoformat(context.payload["starts_at"]),
            party_size=context.payload["party_size"],
        )
        return {"booking_id": str(booking.id), "status": booking.status.value}


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
        ]

    def appliers(self) -> dict[str, ActionApplier]:
        return {BookingCreateApplier.KIND: BookingCreateApplier(self._context)}

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
        proposals.hold(
            Proposal(
                kind=BookingCreateApplier.KIND,
                payload={
                    "table_id": str(table_id),
                    "starts_at": starts_at.isoformat(),
                    "party_size": party_size,
                },
                card=card,
            )
        )
        return tool_result({"status": "awaiting_confirmation", "card": dataclasses.asdict(card)})

    def _booking_card(self, booking: BookingView) -> Card:
        start = self._schedule.to_local(booking.starts_at)
        end = self._schedule.to_local(booking.ends_at)
        notice = (
            "Sent as a request; the restaurant confirms it."
            if booking.status == BookingStatus.PENDING
            else None
        )
        return Card(
            title="Book a table",
            fields=[
                CardField(label="Location", value=booking.location.address),
                CardField(
                    label="Table",
                    value=f"{booking.table.label}, up to {booking.table.capacity} guests",
                ),
                CardField(label="Date", value=f"{start:%a, %d %b %Y}"),
                CardField(label="Time", value=f"{start:%H:%M} – {end:%H:%M}"),
                CardField(label="Guests", value=str(booking.party_size)),
            ],
            notice=notice,
            confirm_label="Book",
        )

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
