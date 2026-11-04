from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.services.exceptions import (
    AlreadyVerifiedError,
    CodeExpiredError,
    CodeInvalidError,
    EmailTakenError,
    ResendTooSoonError,
    UserNotFoundError,
)

ERROR_STATUSES: dict[type[DomainError], int] = {
    CodeInvalidError: status.HTTP_400_BAD_REQUEST,
    CodeExpiredError: status.HTTP_400_BAD_REQUEST,
    EmailTakenError: status.HTTP_409_CONFLICT,
    AlreadyVerifiedError: status.HTTP_409_CONFLICT,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
    ResendTooSoonError: status.HTTP_429_TOO_MANY_REQUESTS,
}
