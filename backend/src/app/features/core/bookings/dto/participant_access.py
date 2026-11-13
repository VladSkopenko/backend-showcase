import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ParticipantAccess:
    participant_id: uuid.UUID
    preorder_open: bool
