from dataclasses import dataclass

from app.features.core.auth.enums import VerificationPurpose
from app.features.core.users.models import User


@dataclass(frozen=True)
class IssuedCode:
    user: User
    purpose: VerificationPurpose
    plain_code: str
    debug_code: str | None
