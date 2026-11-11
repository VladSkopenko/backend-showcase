from app.common.errors import DomainError


class EmailTakenError(DomainError):
    code = "EMAIL_TAKEN"

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class UserNotFoundError(DomainError):
    code = "USER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No account with this email exists.")


class AlreadyVerifiedError(DomainError):
    code = "ALREADY_VERIFIED"

    def __init__(self) -> None:
        super().__init__("This email is already verified.")


class ResendTooSoonError(DomainError):
    code = "RESEND_TOO_SOON"

    def __init__(self, retry_after: int) -> None:
        super().__init__("A new code can be requested later.")
        self.retry_after = retry_after


class CodeInvalidError(DomainError):
    code = "CODE_INVALID"

    def __init__(self) -> None:
        super().__init__("The code is wrong or no longer valid.")


class CodeExpiredError(DomainError):
    code = "CODE_EXPIRED"

    def __init__(self) -> None:
        super().__init__("The code has expired. Request a new one.")


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("The email or password is wrong.")


class EmailNotVerifiedError(DomainError):
    code = "EMAIL_NOT_VERIFIED"

    def __init__(self) -> None:
        super().__init__("Confirm your email before signing in.")


class AccountLockedError(DomainError):
    code = "ACCOUNT_LOCKED"

    def __init__(self, retry_after: int, lockout_minutes: int) -> None:
        super().__init__(f"Too many failed attempts. Try again in {lockout_minutes} minutes.")
        self.retry_after = retry_after


class NotAuthenticatedError(DomainError):
    code = "NOT_AUTHENTICATED"

    def __init__(self) -> None:
        super().__init__("Sign in to continue.")


class SessionInvalidError(DomainError):
    code = "SESSION_INVALID"

    def __init__(self) -> None:
        super().__init__("The session has ended. Sign in again.")


class OAuthCancelledError(DomainError):
    code = "OAUTH_CANCELLED"

    def __init__(self) -> None:
        super().__init__("Sign-in was cancelled.")


class OAuthEmailUnverifiedError(DomainError):
    code = "OAUTH_EMAIL_UNVERIFIED"

    def __init__(self) -> None:
        super().__init__("The provider did not confirm an email for this account.")


class OAuthAccountConflictError(DomainError):
    code = "OAUTH_ACCOUNT_CONFLICT"

    def __init__(self) -> None:
        super().__init__("This account is already linked to another provider account.")


class OAuthUnavailableError(DomainError):
    code = "OAUTH_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("This sign-in method is not available.")


class OAuthFailedError(DomainError):
    code = "OAUTH_FAILED"

    def __init__(self) -> None:
        super().__init__("Sign-in failed. Try again.")
