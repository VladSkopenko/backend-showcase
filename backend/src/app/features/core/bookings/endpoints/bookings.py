import uuid
from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.common.error_responses import error_responses
from app.features.core.auth.endpoints.dependencies import CurrentUserDep
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.dependencies import (
    BookingServiceDep,
    TableSearchServiceDep,
)
from app.features.core.bookings.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.core.bookings.endpoints.openapi_tags import BookingOpenApiTags
from app.features.core.bookings.schemas import (
    BookingResponse,
    CreateBookingRequest,
    TableCardPageResponse,
)
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingNotFoundError,
    CancellationClosedError,
    DateOutOfRangeError,
    OverlappingBookingError,
    PartyTooLargeError,
    SlotInvalidError,
    SlotUnavailableError,
    TableNotFoundError,
    TableNotSuitableError,
)
from app.features.core.locations.services.exceptions import LocationNotFoundError

router = APIRouter(prefix="/bookings", tags=[BookingOpenApiTags.BOOKING])


@router.get(
    "/tables",
    response_model=TableCardPageResponse,
    responses=error_responses(
        PartyTooLargeError,
        DateOutOfRangeError,
        SlotInvalidError,
        LocationNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Lists the tables that can be booked online for the party on that date, optionally at "
        "one location, each with its full day grid of start times and whether each is free. "
        "Without `time` a table is listed when any start is free; with `time`, only when that "
        "start is free. Dates run from today to the booking horizon. Ordered by location, then "
        "table number; `limit` is 20 by default and at most 50. No sign-in needed."
    ),
)
async def search_tables(
    search: TableSearchServiceDep,
    day: Annotated[date, Query(alias="date")],
    party_size: Annotated[int, Query(ge=1)],
    location_id: uuid.UUID | None = None,
    slot_time: Annotated[time | None, Query(alias="time")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> TableCardPageResponse:
    page = await search.search(
        day=day,
        party_size=party_size,
        location_id=location_id,
        slot_time=slot_time,
        limit=limit,
        offset=offset,
    )
    return TableCardPageResponse.model_validate(page)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BookingResponse,
    responses=error_responses(
        NotAuthenticatedError,
        PartyTooLargeError,
        DateOutOfRangeError,
        SlotInvalidError,
        TableNotFoundError,
        TableNotSuitableError,
        SlotUnavailableError,
        OverlappingBookingError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Books a table for the signed-in user at one start of the day grid; the booking is "
        "confirmed at once and holds the table for a fixed duration. `starts_at` may carry any "
        "offset. Refused when the table or the user already has a booking at that time."
    ),
)
async def create_booking(
    body: CreateBookingRequest, user: CurrentUserDep, bookings: BookingServiceDep
) -> BookingResponse:
    booking = await bookings.create(
        user_id=user.id,
        table_id=body.table_id,
        starts_at=body.starts_at,
        party_size=body.party_size,
    )
    return BookingResponse.model_validate(booking)


@router.get(
    "",
    response_model=list[BookingResponse],
    responses=error_responses(
        NotAuthenticatedError, statuses=DOCUMENTED_ERROR_STATUSES, takes_input=True
    ),
    description=(
        "Lists the signed-in user's bookings in every status, latest start first; not paginated."
    ),
)
async def list_bookings(user: CurrentUserDep, bookings: BookingServiceDep) -> list[BookingResponse]:
    return [
        BookingResponse.model_validate(booking)
        for booking in await bookings.list_for_user(user_id=user.id)
    ]


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        BookingAlreadyCancelledError,
        CancellationClosedError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Cancels one of the signed-in user's confirmed bookings and frees its table. Closes "
        "shortly before the start; another user's booking answers 404."
    ),
)
async def cancel_booking(
    booking_id: uuid.UUID, user: CurrentUserDep, bookings: BookingServiceDep
) -> BookingResponse:
    return BookingResponse.model_validate(
        await bookings.cancel(user_id=user.id, booking_id=booking_id)
    )
