from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.notifications.services.exceptions import NotificationNotFoundError

ERROR_STATUSES: dict[type[DomainError], int] = {
    NotificationNotFoundError: status.HTTP_404_NOT_FOUND,
}

# The routes also document the sign-in error raised by the auth feature they build on.
DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
}
