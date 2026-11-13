import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.features.core.bookings.enums import BookingStatus, ParticipantRole


class BookingLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    image_url: str


class BookingTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    capacity: int


class SlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    starts_at: datetime
    available: bool


class TableCardResponse(BookingTableResponse):
    location: BookingLocationResponse
    slots: list[SlotResponse]


class TableCardPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[TableCardResponse]
    total: int
    limit: int
    offset: int


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: ParticipantRole


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: BookingStatus
    party_size: int
    starts_at: datetime
    ends_at: datetime
    table: BookingTableResponse
    location: BookingLocationResponse
    role: ParticipantRole
    participant_id: uuid.UUID
    participants: list[ParticipantResponse]


class CreateBookingRequest(BaseModel):
    table_id: uuid.UUID
    starts_at: AwareDatetime
    party_size: Annotated[int, Field(ge=1)]


class EditBookingRequest(BaseModel):
    starts_at: AwareDatetime
    party_size: Annotated[int, Field(ge=1)]
    duration_minutes: int
