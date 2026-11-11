from typing import ClassVar


class DomainError(Exception):
    code: ClassVar[str]
    retry_after: int | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
