from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingFullError,
    BookingNotFoundError,
    BookingPendingError,
    BookingRejectedError,
    CancellationClosedError,
    DateOutOfRangeError,
    DayChangeNotAllowedError,
    DurationInvalidError,
    EditClosedError,
    EndsAfterClosingError,
    GuestNameRequiredError,
    InviteClosedError,
    LargeBookingNotEditableError,
    OverlappingBookingError,
    PartyBelowParticipantsError,
    PartyTooLargeError,
    RequestExpiredError,
    RequestNotPendingError,
    RequestTooLateError,
    SlotInvalidError,
    SlotUnavailableError,
    StaffOnlyError,
    TableNotFoundError,
    TableNotSuitableError,
)
from app.features.core.locations.endpoints.errors import ERROR_STATUSES as LOCATIONS_ERROR_STATUSES
from app.features.core.locations.services.exceptions import LocationNotFoundError

ERROR_STATUSES: dict[type[DomainError], int] = {
    PartyTooLargeError: status.HTTP_400_BAD_REQUEST,
    DateOutOfRangeError: status.HTTP_400_BAD_REQUEST,
    SlotInvalidError: status.HTTP_400_BAD_REQUEST,
    TableNotFoundError: status.HTTP_404_NOT_FOUND,
    TableNotSuitableError: status.HTTP_400_BAD_REQUEST,
    SlotUnavailableError: status.HTTP_409_CONFLICT,
    OverlappingBookingError: status.HTTP_409_CONFLICT,
    BookingNotFoundError: status.HTTP_404_NOT_FOUND,
    BookingAlreadyCancelledError: status.HTTP_409_CONFLICT,
    BookingPendingError: status.HTTP_409_CONFLICT,
    CancellationClosedError: status.HTTP_409_CONFLICT,
    EditClosedError: status.HTTP_409_CONFLICT,
    DayChangeNotAllowedError: status.HTTP_400_BAD_REQUEST,
    DurationInvalidError: status.HTTP_400_BAD_REQUEST,
    EndsAfterClosingError: status.HTTP_400_BAD_REQUEST,
    InviteClosedError: status.HTTP_409_CONFLICT,
    BookingFullError: status.HTTP_409_CONFLICT,
    GuestNameRequiredError: status.HTTP_400_BAD_REQUEST,
    PartyBelowParticipantsError: status.HTTP_409_CONFLICT,
    BookingRejectedError: status.HTTP_409_CONFLICT,
    LargeBookingNotEditableError: status.HTTP_409_CONFLICT,
    StaffOnlyError: status.HTTP_403_FORBIDDEN,
    RequestNotPendingError: status.HTTP_409_CONFLICT,
    RequestExpiredError: status.HTTP_409_CONFLICT,
    RequestTooLateError: status.HTTP_409_CONFLICT,
}

# The routes also document errors raised by the auth and locations features they build on.
DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    LocationNotFoundError: LOCATIONS_ERROR_STATUSES[LocationNotFoundError],
}
