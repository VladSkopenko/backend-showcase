import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import BookingSettings
from app.features.core.bookings.dto import SlotView, TableCardPage, TableCardView
from app.features.core.bookings.models import Booking
from app.features.core.bookings.repositories import BookableTableRepository, BookingRepository
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.locations.dto import LocationView
from app.features.core.locations.models import DiningTable
from app.features.core.locations.services.exceptions import LocationNotFoundError
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class TableSearchService:
    def __init__(
        self, session: AsyncSession, locations: LocationCatalogService, settings: BookingSettings
    ) -> None:
        self._tables = BookableTableRepository(session)
        self._bookings = BookingRepository(session)
        self._locations = locations
        self._schedule = BookingSchedule(settings)

    async def search(
        self,
        *,
        day: date,
        party_size: int,
        location_id: uuid.UUID | None,
        slot_time: time | None,
        limit: int,
        offset: int,
    ) -> TableCardPage:
        self._schedule.check_party_size(party_size=party_size)
        self._schedule.check_date(day=day)
        if slot_time is not None:
            self._schedule.check_slot_time(slot_time=slot_time)
        locations = {location.id: location for location in await self._locations.list_all()}
        if location_id is not None and location_id not in locations:
            raise LocationNotFoundError()
        tables = await self._tables.list_fitting(
            min_capacity=party_size,
            max_capacity=self._schedule.max_party_size,
            location_id=location_id,
        )
        starts = self._schedule.starts_on(day=day)
        booked: defaultdict[uuid.UUID, list[Booking]] = defaultdict(list)
        for booking in await self._bookings.list_confirmed_overlapping(
            table_ids=[table.id for table in tables],
            starts_at=starts[0],
            ends_at=starts[-1] + self._schedule.duration,
        ):
            booked[booking.table_id].append(booking)
        wanted = (
            None if slot_time is None else self._schedule.start_at(day=day, slot_time=slot_time)
        )
        now = self._schedule.now()
        cards = [
            self._to_card(table, locations[table.location_id], starts, booked[table.id], now)
            for table in tables
        ]
        matching = [card for card in cards if self._is_wanted(card, wanted)]
        return TableCardPage(
            items=matching[offset : offset + limit],
            total=len(matching),
            limit=limit,
            offset=offset,
        )

    def _to_card(
        self,
        table: DiningTable,
        location: LocationView,
        starts: Sequence[datetime],
        bookings: Sequence[Booking],
        now: datetime,
    ) -> TableCardView:
        return TableCardView(
            id=table.id,
            label=table.label,
            capacity=table.capacity,
            location=location,
            slots=[
                SlotView(starts_at=start, available=self._is_free(start, bookings, now))
                for start in starts
            ],
        )

    def _is_free(self, start: datetime, bookings: Sequence[Booking], now: datetime) -> bool:
        end = start + self._schedule.duration
        return start > now and not any(
            booking.starts_at < end and booking.ends_at > start for booking in bookings
        )

    @staticmethod
    def _is_wanted(card: TableCardView, wanted: datetime | None) -> bool:
        return any(
            slot.available and (wanted is None or slot.starts_at == wanted) for slot in card.slots
        )
