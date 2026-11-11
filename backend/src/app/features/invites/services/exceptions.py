from app.common.errors import DomainError


class InviteNotFoundError(DomainError):
    code = "INVITE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No invitation with this code exists.")
