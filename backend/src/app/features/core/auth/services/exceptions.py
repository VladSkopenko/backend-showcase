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
