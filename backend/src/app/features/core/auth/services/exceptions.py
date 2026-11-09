from app.common.errors import DomainError


class EmailTakenError(DomainError):
    def __init__(self) -> None:
        super().__init__("EMAIL_TAKEN", "An account with this email already exists.")


class UserNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("USER_NOT_FOUND", "No account with this email exists.")


class AlreadyVerifiedError(DomainError):
    def __init__(self) -> None:
        super().__init__("ALREADY_VERIFIED", "This email is already verified.")


class ResendTooSoonError(DomainError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("RESEND_TOO_SOON", "A new code can be requested later.")
        self.retry_after = retry_after


class CodeInvalidError(DomainError):
    def __init__(self) -> None:
        super().__init__("CODE_INVALID", "The code is wrong or no longer valid.")


class CodeExpiredError(DomainError):
    def __init__(self) -> None:
        super().__init__("CODE_EXPIRED", "The code has expired. Request a new one.")


class InvalidCredentialsError(DomainError):
    def __init__(self) -> None:
        super().__init__("INVALID_CREDENTIALS", "The email or password is wrong.")


class EmailNotVerifiedError(DomainError):
    def __init__(self) -> None:
        super().__init__("EMAIL_NOT_VERIFIED", "Confirm your email before signing in.")


class AccountLockedError(DomainError):
    def __init__(self, lockout_minutes: int) -> None:
        super().__init__(
            "ACCOUNT_LOCKED", f"Too many failed attempts. Try again in {lockout_minutes} minutes."
        )


class NotAuthenticatedError(DomainError):
    def __init__(self) -> None:
        super().__init__("NOT_AUTHENTICATED", "Sign in to continue.")


class SessionInvalidError(DomainError):
    def __init__(self) -> None:
        super().__init__("SESSION_INVALID", "The session has ended. Sign in again.")


class OAuthCancelledError(DomainError):
    def __init__(self) -> None:
        super().__init__("OAUTH_CANCELLED", "Sign-in was cancelled.")


class OAuthEmailUnverifiedError(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "OAUTH_EMAIL_UNVERIFIED", "The provider did not confirm an email for this account."
        )


class OAuthAccountConflictError(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "OAUTH_ACCOUNT_CONFLICT", "This account is already linked to another provider account."
        )


class OAuthUnavailableError(DomainError):
    def __init__(self) -> None:
        super().__init__("OAUTH_UNAVAILABLE", "This sign-in method is not available.")


class OAuthFailedError(DomainError):
    def __init__(self) -> None:
        super().__init__("OAUTH_FAILED", "Sign-in failed. Try again.")
