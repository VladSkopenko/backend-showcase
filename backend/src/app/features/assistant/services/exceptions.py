from app.common.errors import DomainError


class AssistantUnavailableError(DomainError):
    code = "ASSISTANT_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("The assistant is not available.")


class AssistantSessionNotFoundError(DomainError):
    code = "ASSISTANT_SESSION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No chat with this id exists.")


# Raised inside a running stream, where no HTTP status applies: the turn service turns them into
# `error` events and owns their codes.
class AssistantTurnTimeoutError(Exception):
    pass


class AssistantProviderError(Exception):
    pass
