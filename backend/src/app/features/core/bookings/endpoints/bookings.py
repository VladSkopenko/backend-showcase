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
    EditBookingRequest,
    SlotResponse,
    TableCardPageResponse,
)
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingNotFoundError,
    CancellationClosedError,
    DateOutOfRangeError,
    DayChangeNotAllowedError,
    DurationInvalidError,
    EditClosedError,
    EndsAfterClosingError,
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


@router.put(
    "/{booking_id}",
    response_model=BookingResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        BookingAlreadyCancelledError,
        EditClosedError,
        PartyTooLargeError,
        DayChangeNotAllowedError,
        SlotInvalidError,
        DurationInvalidError,
        EndsAfterClosingError,
        TableNotSuitableError,
        SlotUnavailableError,
        OverlappingBookingError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Replaces the start, party size and duration of one of the signed-in user's confirmed "
        "bookings; the table and the day stay. The start must be on the day grid and the stay "
        "must end by closing; durations run from the standard one to a maximum in grid steps. "
        "Closes shortly before the current start; another user's booking answers 404. Refused "
        "when the table or the user already has another booking at the new time."
    ),
)
async def edit_booking(
    booking_id: uuid.UUID,
    body: EditBookingRequest,
    user: CurrentUserDep,
    bookings: BookingServiceDep,
) -> BookingResponse:
    booking = await bookings.edit(
        user_id=user.id,
        booking_id=booking_id,
        starts_at=body.starts_at,
        party_size=body.party_size,
        duration_minutes=body.duration_minutes,
    )
    return BookingResponse.model_validate(booking)


@router.get(
    "/{booking_id}/slots",
    response_model=list[SlotResponse],
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        BookingAlreadyCancelledError,
        EditClosedError,
        DurationInvalidError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Lists the day grid of one of the signed-in user's confirmed bookings on its table for a "
        "stay of `duration_minutes`, and whether the booking can move to each start: later than "
        "now, ending by closing and free of other bookings on the table. The booking itself and "
        "the user's other bookings are ignored. Closes shortly before the current start."
    ),
)
async def list_edit_slots(
    booking_id: uuid.UUID,
    duration_minutes: int,
    user: CurrentUserDep,
    bookings: BookingServiceDep,
) -> list[SlotResponse]:
    return [
        SlotResponse.model_validate(slot)
        for slot in await bookings.list_edit_slots(
            user_id=user.id, booking_id=booking_id, duration_minutes=duration_minutes
        )
    ]
