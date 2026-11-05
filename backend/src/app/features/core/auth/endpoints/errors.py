from fastapi import status

from app.common.errors import DomainError
from app.features.core.auth.services.exceptions import (
    AccountLockedError,
    AlreadyVerifiedError,
    CodeExpiredError,
    CodeInvalidError,
    EmailNotVerifiedError,
    EmailTakenError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    ResendTooSoonError,
    SessionInvalidError,
    UserNotFoundError,
)

ERROR_STATUSES: dict[type[DomainError], int] = {
    CodeInvalidError: status.HTTP_400_BAD_REQUEST,
    CodeExpiredError: status.HTTP_400_BAD_REQUEST,
    EmailTakenError: status.HTTP_409_CONFLICT,
    AlreadyVerifiedError: status.HTTP_409_CONFLICT,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
    ResendTooSoonError: status.HTTP_429_TOO_MANY_REQUESTS,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    NotAuthenticatedError: status.HTTP_401_UNAUTHORIZED,
    SessionInvalidError: status.HTTP_401_UNAUTHORIZED,
    EmailNotVerifiedError: status.HTTP_403_FORBIDDEN,
    AccountLockedError: status.HTTP_423_LOCKED,
}
