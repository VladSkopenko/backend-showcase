from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.features.core.bookings.schemas import BookingLocationResponse, BookingTableResponse

GuestName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]


class InviteLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str


class InvitePreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner_first_name: str
    starts_at: datetime
    ends_at: datetime
    party_size: int
    table: BookingTableResponse
    location: BookingLocationResponse


class JoinInviteRequest(BaseModel):
    name: GuestName | None = None
