import datetime
import uuid

from pydantic import BaseModel, Field, field_validator


class LocalTimeArguments(BaseModel):
    """Arguments whose `time` is restaurant-local: an offset would be dropped silently."""

    @field_validator("time", check_fields=False)
    @classmethod
    def time_without_offset(cls, value: datetime.time | None) -> datetime.time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("give the time as HH:MM in the restaurant's timezone, no offset")
        return value


class FindTablesArguments(BaseModel):
    date: datetime.date = Field(
        description="The day of the visit in the restaurant's timezone, as YYYY-MM-DD."
    )
    party_size: int = Field(ge=1, description="How many people come, the guest included.")
    location_id: uuid.UUID | None = Field(
        default=None,
        description="Only tables at this location, by the id list_locations returns. Omit for all.",
    )
    time: datetime.time | None = Field(
        default=None,
        description=(
            "Only tables free at this start, as HH:MM in the restaurant's timezone on the slot "
            "grid. Omit to see every free start of the day."
        ),
    )


class ListMyBookingsArguments(BaseModel):
    pass


class CreateBookingArguments(LocalTimeArguments):
    table_id: uuid.UUID = Field(description="The table to book, by the id find_tables returns.")
    date: datetime.date = Field(
        description="The day of the visit in the restaurant's timezone, as YYYY-MM-DD."
    )
    time: datetime.time = Field(
        description=(
            "The start of the visit, as HH:MM in the restaurant's timezone on the slot grid."
        )
    )
    party_size: int = Field(ge=1, description="How many people come, the guest included.")


class EditBookingArguments(LocalTimeArguments):
    booking_id: uuid.UUID = Field(
        description="The booking to change, by the id list_my_bookings returns."
    )
    time: datetime.time | None = Field(
        default=None,
        description=(
            "The new start on the same day, as HH:MM in the restaurant's timezone on the slot "
            "grid. Omit to keep the current start."
        ),
    )
    party_size: int | None = Field(
        default=None,
        ge=1,
        description="The new number of people, the guest included. Omit to keep the current one.",
    )
    duration_minutes: int | None = Field(
        default=None,
        description="The new length of the visit in minutes. Omit to keep the current one.",
    )


class CancelBookingArguments(BaseModel):
    booking_id: uuid.UUID = Field(
        description="The booking to cancel, by the id list_my_bookings returns."
    )
