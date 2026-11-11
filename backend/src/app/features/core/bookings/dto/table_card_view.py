import uuid
from dataclasses import dataclass

from app.features.core.bookings.dto.slot_view import SlotView
from app.features.core.locations.dto import LocationView


@dataclass(frozen=True)
class TableCardView:
    id: uuid.UUID
    label: str
    capacity: int
    location: LocationView
    slots: list[SlotView]
