from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.errors import ERROR_STATUSES as BOOKINGS_ERROR_STATUSES
from app.features.core.bookings.services.exceptions import BookingNotFoundError
from app.features.core.menu.endpoints.errors import ERROR_STATUSES as MENU_ERROR_STATUSES
from app.features.core.menu.services.exceptions import DishNotFoundError
from app.features.preorder.services.exceptions import (
    CartEmptyError,
    CartItemNotFoundError,
    DishUnavailableError,
    PreorderClosedError,
    QuantityTooLargeError,
)

ERROR_STATUSES: dict[type[DomainError], int] = {
    PreorderClosedError: status.HTTP_409_CONFLICT,
    QuantityTooLargeError: status.HTTP_400_BAD_REQUEST,
    DishUnavailableError: status.HTTP_409_CONFLICT,
    CartItemNotFoundError: status.HTTP_404_NOT_FOUND,
    CartEmptyError: status.HTTP_409_CONFLICT,
}

DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    BookingNotFoundError: BOOKINGS_ERROR_STATUSES[BookingNotFoundError],
    DishNotFoundError: MENU_ERROR_STATUSES[DishNotFoundError],
}
