from dataclasses import dataclass

from app.features.core.users.models import User


@dataclass(frozen=True)
class IssuedCode:
    user: User
    plain_code: str
    debug_code: str | None
