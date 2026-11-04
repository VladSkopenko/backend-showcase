class DomainError(Exception):
    retry_after: int | None = None

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
