import math
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.config.settings import AuthSettings
from app.features.core.auth.dto import LoginOutcome
from app.features.core.auth.services.exceptions import (
    AccountLockedError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
)
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.session_service import SessionService
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class LoginService:
    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        session_service: SessionService,
        auth: AuthSettings,
    ) -> None:
        self._user_repository = UserRepository(session)
        self._password_hasher = password_hasher
        self._session_service = session_service
        self._auth = auth

    async def log_in(self, *, email: str, password: str) -> LoginOutcome:
        # Failures that change the counter are returned, not raised: raising would roll back the
        # counted attempt or the reset together with the request.
        user = await self._user_repository.get_by_email(email=email, for_update=True)
        if user is None or user.password_hash is None:
            raise InvalidCredentialsError()
        now = clock.now()
        if user.login_locked_until is not None and user.login_locked_until > now:
            raise self._locked_error(locked_until=user.login_locked_until, now=now)
        if not await self._password_hasher.verify(
            password=password, password_hash=user.password_hash
        ):
            return LoginOutcome(user=user, error=self._count_failure(user=user, now=now))
        user.failed_login_attempts = 0
        if user.email_verified_at is None:
            return LoginOutcome(user=user, error=EmailNotVerifiedError())
        return LoginOutcome(user=user, session=await self._session_service.start(user=user))

    def _count_failure(
        self, *, user: User, now: datetime
    ) -> InvalidCredentialsError | AccountLockedError:
        user.failed_login_attempts += 1
        if user.failed_login_attempts < self._auth.max_login_attempts:
            return InvalidCredentialsError()
        user.failed_login_attempts = 0
        user.login_locked_until = now + timedelta(minutes=self._auth.login_lockout_minutes)
        return self._locked_error(locked_until=user.login_locked_until, now=now)

    def _locked_error(self, *, locked_until: datetime, now: datetime) -> AccountLockedError:
        return AccountLockedError(
            retry_after=math.ceil((locked_until - now).total_seconds()),
            lockout_minutes=self._auth.login_lockout_minutes,
        )
