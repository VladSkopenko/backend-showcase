from dataclasses import dataclass

from app.common.errors import DomainError
from app.features.core.auth.dto.issued_session import IssuedSession


@dataclass(frozen=True)
class OAuthSignInOutcome:
    session: IssuedSession | None = None
    error: DomainError | None = None
