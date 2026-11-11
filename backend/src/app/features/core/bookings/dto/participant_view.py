import uuid
from dataclasses import dataclass

from app.features.core.bookings.enums import ParticipantRole


@dataclass(frozen=True)
class ParticipantView:
    id: uuid.UUID
    name: str
    role: ParticipantRole
