from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingFullError,
    BookingNotFoundError,
    CancellationClosedError,
    DateOutOfRangeError,
    DayChangeNotAllowedError,
    DurationInvalidError,
    EditClosedError,
    EndsAfterClosingError,
    GuestNameRequiredError,
    InviteClosedError,
    OverlappingBookingError,
    PartyBelowParticipantsError,
    PartyTooLargeError,
    SlotInvalidError,
    SlotUnavailableError,
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
    CancellationClosedError: status.HTTP_409_CONFLICT,
    EditClosedError: status.HTTP_409_CONFLICT,
    DayChangeNotAllowedError: status.HTTP_400_BAD_REQUEST,
    DurationInvalidError: status.HTTP_400_BAD_REQUEST,
    EndsAfterClosingError: status.HTTP_400_BAD_REQUEST,
    InviteClosedError: status.HTTP_409_CONFLICT,
    BookingFullError: status.HTTP_409_CONFLICT,
    GuestNameRequiredError: status.HTTP_400_BAD_REQUEST,
    PartyBelowParticipantsError: status.HTTP_409_CONFLICT,
}

# The routes also document errors raised by the auth and locations features they build on.
DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    LocationNotFoundError: LOCATIONS_ERROR_STATUSES[LocationNotFoundError],
}
