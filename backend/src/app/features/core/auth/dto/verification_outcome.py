from dataclasses import dataclass

from app.common.errors import DomainError
from app.features.core.users.models import User


@dataclass(frozen=True)
class VerificationOutcome:
    user: User
    error: DomainError | None = None
