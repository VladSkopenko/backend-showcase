import uuid

from pydantic import BaseModel, Field


class GetMyPreorderArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The id of one of the guest's bookings, as list_my_bookings returns it."
    )
