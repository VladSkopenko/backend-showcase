import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.bookings.dto import BookedTableView, BookingView, ParticipantView
from app.features.core.bookings.enums import ParticipantRole
from app.features.core.bookings.models import Booking
from app.features.core.bookings.repositories import BookingParticipantRepository
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.locations.dto import LocationView
from app.features.core.locations.models import DiningTable
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingViewBuilder:
    def __init__(
        self, session: AsyncSession, locations: LocationCatalogService, schedule: BookingSchedule
    ) -> None:
        self._participants = BookingParticipantRepository(session)
        self._locations = locations
        self._schedule = schedule

    async def one(
        self,
        *,
        booking: Booking,
        table: DiningTable,
        role: ParticipantRole,
        participant_id: uuid.UUID,
    ) -> BookingView:
        location = await self._locations.get(location_id=table.location_id)
        participants = await self._participants_of(booking_ids=[booking.id])
        return self._to_view(
            booking, table, location, role, participant_id, participants[booking.id]
        )

    async def many(
        self, *, rows: Sequence[tuple[Booking, DiningTable, ParticipantRole, uuid.UUID]]
    ) -> list[BookingView]:
        locations = {location.id: location for location in await self._locations.list_all()}
        participants = await self._participants_of(
            booking_ids=[booking.id for booking, _, _, _ in rows]
        )
        return [
            self._to_view(
                booking,
                table,
                locations[table.location_id],
                role,
                participant_id,
                participants[booking.id],
            )
            for booking, table, role, participant_id in rows
        ]

    async def _participants_of(
        self, *, booking_ids: Sequence[uuid.UUID]
    ) -> defaultdict[uuid.UUID, list[ParticipantView]]:
        grouped: defaultdict[uuid.UUID, list[ParticipantView]] = defaultdict(list)
        for participant, name in await self._participants.list_named(booking_ids=booking_ids):
            grouped[participant.booking_id].append(
                ParticipantView(id=participant.id, name=name, role=participant.role)
            )
        return grouped

    def _to_view(
        self,
        booking: Booking,
        table: DiningTable,
        location: LocationView,
        role: ParticipantRole,
        participant_id: uuid.UUID,
        participants: list[ParticipantView],
    ) -> BookingView:
        return BookingView(
            id=booking.id,
            status=booking.status,
            party_size=booking.party_size,
            starts_at=self._schedule.to_local(booking.starts_at),
            ends_at=self._schedule.to_local(booking.ends_at),
            table=BookedTableView(id=table.id, label=table.label, capacity=table.capacity),
            location=location,
            role=role,
            participant_id=participant_id,
            participants=participants,
        )
