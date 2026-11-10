import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class LocationView:
    id: uuid.UUID
    address: str
    image_url: str
    table_count: int
    description: str
