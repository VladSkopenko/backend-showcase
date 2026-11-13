from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.errors import ERROR_STATUSES as BOOKINGS_ERROR_STATUSES
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingFullError,
    BookingNotFoundError,
    BookingRejectedError,
    GuestNameRequiredError,
    InviteClosedError,
)
from app.features.invites.services.exceptions import InviteNotFoundError

ERROR_STATUSES: dict[type[DomainError], int] = {
    InviteNotFoundError: status.HTTP_404_NOT_FOUND,
}

DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    BookingNotFoundError: BOOKINGS_ERROR_STATUSES[BookingNotFoundError],
    BookingAlreadyCancelledError: BOOKINGS_ERROR_STATUSES[BookingAlreadyCancelledError],
    BookingRejectedError: BOOKINGS_ERROR_STATUSES[BookingRejectedError],
    InviteClosedError: BOOKINGS_ERROR_STATUSES[InviteClosedError],
    BookingFullError: BOOKINGS_ERROR_STATUSES[BookingFullError],
    GuestNameRequiredError: BOOKINGS_ERROR_STATUSES[GuestNameRequiredError],
}
