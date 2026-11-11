from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SlotView:
    starts_at: datetime
    available: bool
