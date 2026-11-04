from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.auth.dto import IssuedCode, VerificationOutcome
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.services.exceptions import AlreadyVerifiedError, UserNotFoundError
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class EmailVerificationService:
    def __init__(self, session: AsyncSession, code_service: VerificationCodeService) -> None:
        self._user_repository = UserRepository(session)
        self._code_service = code_service

    async def verify(self, *, email: str, code: str) -> VerificationOutcome:
        # A wrong or expired code is returned, not raised: raising would roll back the counted
        # attempt together with the request.
        user = await self._lock_unverified_user(email=email)
        error = await self._code_service.consume(
            user=user, purpose=VerificationPurpose.EMAIL_VERIFICATION, code=code
        )
        if error is not None:
            return VerificationOutcome(user=user, error=error)
        user.email_verified_at = clock.now()
        return VerificationOutcome(user=user)

    async def resend(self, *, email: str) -> IssuedCode:
        user = await self._lock_unverified_user(email=email)
        return await self._code_service.issue(
            user=user, purpose=VerificationPurpose.EMAIL_VERIFICATION
        )

    async def _lock_unverified_user(self, *, email: str) -> User:
        user = await self._user_repository.get_by_email(email=email, for_update=True)
        if user is None:
            raise UserNotFoundError()
        if user.email_verified_at is not None:
            raise AlreadyVerifiedError()
        return user
