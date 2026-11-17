from dataclasses import dataclass

from app.features.preorder.dto.participant_preorder_view import ParticipantPreorderView


@dataclass(frozen=True)
class GroupPreorderView:
    participants: list[ParticipantPreorderView]
    total_cents: int
