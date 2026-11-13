import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.common.error_responses import error_responses
from app.features.core.auth.endpoints.dependencies import CurrentUserDep
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.dependencies import BookingRequestServiceDep
from app.features.core.bookings.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.core.bookings.endpoints.openapi_tags import BookingOpenApiTags
from app.features.core.bookings.schemas import BookingRequestPageResponse, BookingRequestResponse
from app.features.core.bookings.services.exceptions import (
    BookingNotFoundError,
    RequestExpiredError,
    RequestNotPendingError,
    SlotUnavailableError,
    StaffOnlyError,
)

router = APIRouter(prefix="/staff/booking-requests", tags=[BookingOpenApiTags.STAFF])


@router.get(
    "",
    response_model=BookingRequestPageResponse,
    responses=error_responses(
        NotAuthenticatedError, StaffOnlyError, statuses=DOCUMENTED_ERROR_STATUSES, takes_input=True
    ),
    description=(
        "Lists the pending large-party requests whose start is still ahead, earliest start "
        "first, then oldest request first. Each shows the owner's first name, the party, the "
        "time, the table, the location and how many other pending requests compete for that "
        "table and time. `limit` is 20 by default and at most 50. Staff only."
    ),
)
async def list_booking_requests(
    user: CurrentUserDep,
    requests: BookingRequestServiceDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    # Bounded by PostgreSQL bigint: a larger offset overflows in asyncpg and would be a 500.
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> BookingRequestPageResponse:
    page = await requests.list_pending(staff_id=user.id, limit=limit, offset=offset)
    return BookingRequestPageResponse.model_validate(page)


@router.post(
    "/{booking_id}/approve",
    response_model=BookingRequestResponse,
    responses=error_responses(
        NotAuthenticatedError,
        StaffOnlyError,
        BookingNotFoundError,
        RequestNotPendingError,
        RequestExpiredError,
        SlotUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Approves a pending request whose start is still ahead: it becomes a confirmed booking "
        "that holds its table, and every other pending request overlapping it on that table is "
        "rejected. Refused, and the request stays pending, when the table already has a "
        "confirmed booking at that time. Records when and by whom it was decided. Staff only."
    ),
)
async def approve_booking_request(
    booking_id: uuid.UUID, user: CurrentUserDep, requests: BookingRequestServiceDep
) -> BookingRequestResponse:
    return BookingRequestResponse.model_validate(
        await requests.approve(staff_id=user.id, booking_id=booking_id)
    )


@router.post(
    "/{booking_id}/reject",
    response_model=BookingRequestResponse,
    responses=error_responses(
        NotAuthenticatedError,
        StaffOnlyError,
        BookingNotFoundError,
        RequestNotPendingError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Rejects a pending request: it frees the owner's time, and the owner can no longer "
        "cancel, edit or share it. Records when and by whom it was decided. Staff only."
    ),
)
async def reject_booking_request(
    booking_id: uuid.UUID, user: CurrentUserDep, requests: BookingRequestServiceDep
) -> BookingRequestResponse:
    return BookingRequestResponse.model_validate(
        await requests.reject(staff_id=user.id, booking_id=booking_id)
    )
