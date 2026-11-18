import datetime
import uuid

from pydantic import BaseModel, Field


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


class CreateBookingArguments(BaseModel):
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
