import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class GetMyPreorderArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The id of one of the guest's bookings, as list_my_bookings returns it."
    )


class SetCartItemArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The id of one of the guest's bookings, as list_my_bookings returns it."
    )
    dish_id: uuid.UUID = Field(
        description="The dish, by the id list_menu or get_my_preorder returns."
    )
    quantity: int = Field(
        ge=1,
        description=(
            "The new total number of portions of this dish in the cart, not the number to add."
        ),
    )
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = Field(
        default=None,
        description=(
            "A note for the kitchen about this dish. Omit to keep the line's current note; an "
            "empty text removes it."
        ),
    )


class RemoveCartItemArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The id of one of the guest's bookings, as list_my_bookings returns it."
    )
    dish_id: uuid.UUID = Field(
        description="The dish to remove from the cart, by the id get_my_preorder returns."
    )


class SubmitPreorderArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The id of one of the guest's bookings, as list_my_bookings returns it."
    )
