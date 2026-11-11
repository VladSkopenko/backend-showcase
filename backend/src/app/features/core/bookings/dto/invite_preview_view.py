from dataclasses import dataclass
from datetime import datetime

from app.features.core.bookings.dto.booked_table_view import BookedTableView
from app.features.core.locations.dto import LocationView


@dataclass(frozen=True)
class InvitePreviewView:
    owner_first_name: str
    starts_at: datetime
    ends_at: datetime
    party_size: int
    table: BookedTableView
    location: LocationView
