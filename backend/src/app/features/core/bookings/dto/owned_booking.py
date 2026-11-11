import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class OwnedBooking:
    id: uuid.UUID
