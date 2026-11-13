import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.schemas.booking import (
    BookingLocationResponse,
    BookingTableResponse,
)


class BookingRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: BookingStatus
    owner_first_name: str
    party_size: int
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    table: BookingTableResponse
    location: BookingLocationResponse
    competing_requests: int


class BookingRequestPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[BookingRequestResponse]
    total: int
    limit: int
    offset: int
