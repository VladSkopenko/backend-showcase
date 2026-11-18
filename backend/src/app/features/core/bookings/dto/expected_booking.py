from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExpectedBooking:
    starts_at: datetime
    party_size: int
    duration_minutes: int
