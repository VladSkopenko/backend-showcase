from dataclasses import dataclass

from app.common.errors import DomainError
from app.features.core.auth.dto.issued_session import IssuedSession
from app.features.core.users.models import User


@dataclass(frozen=True)
class LoginOutcome:
    user: User
    session: IssuedSession | None = None
    error: DomainError | None = None
