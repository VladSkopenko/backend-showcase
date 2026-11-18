import datetime
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.ai_tools import AiToolContext, invalid_arguments, tool_result
from app.features.core.bookings.ai_tools.arguments import (
    FindTablesArguments,
    ListMyBookingsArguments,
)
from app.features.core.bookings.dto import BookingView, SlotView, TableCardView
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.booking_service import BookingService
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
        ]

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
