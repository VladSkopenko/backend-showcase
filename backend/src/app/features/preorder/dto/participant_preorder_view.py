import uuid
from dataclasses import dataclass

from app.features.core.bookings.enums import ParticipantRole
from app.features.preorder.dto.submitted_part_view import SubmittedPartView


@dataclass(frozen=True)
class ParticipantPreorderView:
    id: uuid.UUID
    name: str
    role: ParticipantRole
    parts: list[SubmittedPartView]
    total_cents: int
