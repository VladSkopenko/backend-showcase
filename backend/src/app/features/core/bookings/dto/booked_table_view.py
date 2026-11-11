import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class BookedTableView:
    id: uuid.UUID
    label: str
    capacity: int
