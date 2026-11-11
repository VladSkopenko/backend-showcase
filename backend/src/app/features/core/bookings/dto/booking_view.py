import uuid
from dataclasses import dataclass
from datetime import datetime

from app.features.core.bookings.dto.booked_table_view import BookedTableView
from app.features.core.bookings.dto.participant_view import ParticipantView
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.features.core.locations.dto import LocationView


@dataclass(frozen=True)
class BookingView:
    id: uuid.UUID
    status: BookingStatus
    party_size: int
    starts_at: datetime
    ends_at: datetime
    table: BookedTableView
    location: LocationView
    role: ParticipantRole
    participants: list[ParticipantView]
