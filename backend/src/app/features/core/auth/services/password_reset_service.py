from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.errors import DomainError
from app.features.core.auth.dto import IssuedCode
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.services.exceptions import UserNotFoundError
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.session_service import SessionService
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class PasswordResetService:
    PURPOSE = VerificationPurpose.PASSWORD_RESET

    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        code_service: VerificationCodeService,
        session_service: SessionService,
    ) -> None:
        self._user_repository = UserRepository(session)
        self._password_hasher = password_hasher
        self._code_service = code_service
        self._session_service = session_service

    async def request(self, *, email: str) -> IssuedCode:
        user = await self._lock_user(email=email)
        return await self._code_service.issue(user=user, purpose=self.PURPOSE)

    async def verify_code(self, *, email: str, code: str) -> DomainError | None:
        # A wrong or expired code is returned, not raised: raising would roll back the counted
        # attempt together with the request.
        user = await self._lock_user(email=email)
        return await self._code_service.check(user=user, purpose=self.PURPOSE, code=code)

    async def confirm(self, *, email: str, code: str, password: str) -> DomainError | None:
        user = await self._lock_user(email=email)
        error = await self._code_service.check(user=user, purpose=self.PURPOSE, code=code)
        if error is not None:
            return error
        password_hash = await self._password_hasher.hash(password=password)
        error = await self._code_service.consume(user=user, purpose=self.PURPOSE, code=code)
        if error is not None:
            return error
        user.password_hash = password_hash
        user.failed_login_attempts = 0
        user.login_locked_until = None
        if user.email_verified_at is None:
            user.email_verified_at = clock.now()
        await self._session_service.revoke_all(user=user)
        return None

    async def _lock_user(self, *, email: str) -> User:
        user = await self._user_repository.get_by_email(email=email, for_update=True)
        if user is None:
            raise UserNotFoundError()
        return user
