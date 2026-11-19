from fastapi import status

from app.common.errors import DomainError
from app.features.assistant.services.exceptions import (
    AssistantActionNotFoundError,
    AssistantActionNotPendingError,
    AssistantBudgetExhaustedError,
    AssistantBusyError,
    AssistantSessionNotFoundError,
    AssistantUnavailableError,
)
from app.features.core.auth.endpoints.errors import ERROR_STATUSES as AUTH_ERROR_STATUSES
from app.features.core.auth.services.exceptions import (
    EmailNotVerifiedError,
    NotAuthenticatedError,
)

ERROR_STATUSES: dict[type[DomainError], int] = {
    AssistantUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    AssistantSessionNotFoundError: status.HTTP_404_NOT_FOUND,
    AssistantActionNotFoundError: status.HTTP_404_NOT_FOUND,
    AssistantActionNotPendingError: status.HTTP_409_CONFLICT,
    AssistantBusyError: status.HTTP_429_TOO_MANY_REQUESTS,
    AssistantBudgetExhaustedError: status.HTTP_429_TOO_MANY_REQUESTS,
}

DOCUMENTED_ERROR_STATUSES: dict[type[DomainError], int] = {
    **ERROR_STATUSES,
    NotAuthenticatedError: AUTH_ERROR_STATUSES[NotAuthenticatedError],
    EmailNotVerifiedError: AUTH_ERROR_STATUSES[EmailNotVerifiedError],
}
