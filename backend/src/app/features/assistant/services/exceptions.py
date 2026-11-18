from app.common.errors import DomainError


class AssistantUnavailableError(DomainError):
    code = "ASSISTANT_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("The assistant is not available.")


class AssistantSessionNotFoundError(DomainError):
    code = "ASSISTANT_SESSION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No chat with this id exists.")


class AssistantActionNotFoundError(DomainError):
    code = "ASSISTANT_ACTION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No card with this id exists in this chat.")


class AssistantActionNotPendingError(DomainError):
    code = "ASSISTANT_ACTION_NOT_PENDING"

    def __init__(self) -> None:
        super().__init__("This card was already applied, cancelled, failed or expired.")


class AssistantBusyError(DomainError):
    code = "ASSISTANT_BUSY"

    def __init__(self, retry_after: int) -> None:
        super().__init__("The assistant is busy. Try again shortly.")
        self.retry_after = retry_after


class AssistantBudgetExhaustedError(DomainError):
    code = "ASSISTANT_BUDGET_EXHAUSTED"

    def __init__(self, retry_after: int) -> None:
        super().__init__("The assistant has reached its limit for today. Try again tomorrow.")
        self.retry_after = retry_after


# Raised inside a running stream, where no HTTP status applies: the turn service turns them into
# `error` events and owns their codes.
class AssistantTurnTimeoutError(Exception):
    pass


class AssistantProviderError(Exception):
    pass
