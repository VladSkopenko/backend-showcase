from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
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
}

# The routes also document errors raised by the auth and locations features they build on.
DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    LocationNotFoundError: LOCATIONS_ERROR_STATUSES[LocationNotFoundError],
}
