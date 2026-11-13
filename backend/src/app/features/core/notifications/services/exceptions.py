from app.common.errors import DomainError


class NotificationNotFoundError(DomainError):
    code = "NOTIFICATION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No notification with this id exists.")
