from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.errors import DomainError
from app.features.core.auth.dto import OAuthIdentity, OAuthSignInOutcome
from app.features.core.auth.enums import OAuthProvider
from app.features.core.auth.models import OAuthAccount
from app.features.core.auth.repositories import OAuthAccountRepository
from app.features.core.auth.services.exceptions import (
    OAuthAccountConflictError,
    OAuthCancelledError,
    OAuthEmailUnverifiedError,
    OAuthFailedError,
    OAuthUnavailableError,
)
from app.features.core.auth.services.oauth_providers import OAuthProviderRegistry
from app.features.core.auth.services.session_service import SessionService
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository
from app.infrastructure.oauth.oauth_exchange_error import OAuthExchangeError


class OAuthSignInService:
    def __init__(
        self,
        session: AsyncSession,
        registry: OAuthProviderRegistry,
        session_service: SessionService,
    ) -> None:
        self._user_repository = UserRepository(session)
        self._account_repository = OAuthAccountRepository(session)
        self._registry = registry
        self._session_service = session_service

    def start(self, *, provider: OAuthProvider) -> DomainError | None:
        if not self._registry.get(provider=provider).is_configured:
            return OAuthUnavailableError()
        return None

    def failure_error(self, *, failure: OAuthExchangeError) -> DomainError:
        if failure.cancelled:
            return OAuthCancelledError()
        return OAuthFailedError()

    async def complete(
        self,
        *,
        provider: OAuthProvider,
        claims: Mapping[str, Any] | None = None,
        failure: OAuthExchangeError | None = None,
    ) -> OAuthSignInOutcome:
        # Every failure is returned with nothing written, so the handler can redirect with its code.
        unavailable = self.start(provider=provider)
        if unavailable is not None:
            return OAuthSignInOutcome(error=unavailable)
        if failure is not None:
            return OAuthSignInOutcome(error=self.failure_error(failure=failure))
        if claims is None:
            return OAuthSignInOutcome(error=OAuthFailedError())
        try:
            identity = self._registry.get(provider=provider).identity(claims=claims)
        except OAuthFailedError as error:
            return OAuthSignInOutcome(error=error)
        user = await self._resolve_user(provider=provider, identity=identity)
        if isinstance(user, DomainError):
            return OAuthSignInOutcome(error=user)
        return OAuthSignInOutcome(session=await self._session_service.start(user=user))

    async def _resolve_user(
        self, *, provider: OAuthProvider, identity: OAuthIdentity
    ) -> User | DomainError:
        account = await self._account_repository.get_by_subject(
            provider=provider, subject=identity.subject
        )
        if account is not None:
            linked = await self._user_repository.get_by_id(user_id=account.user_id)
            return linked if linked is not None else OAuthFailedError()
        if identity.email is None or not identity.email_verified:
            return OAuthEmailUnverifiedError()
        now = clock.now()
        user = await self._user_repository.get_by_email(email=identity.email, for_update=True)
        if user is None:
            user = User(
                first_name=identity.first_name,
                last_name=identity.last_name,
                email=identity.email,
                email_verified_at=now,
            )
            await self._user_repository.add(user=user)
        else:
            if await self._account_repository.get_by_user(user_id=user.id, provider=provider):
                return OAuthAccountConflictError()
            if user.email_verified_at is None:
                # Whoever pre-registered the address loses its password; the owner can reset one.
                user.email_verified_at = now
                user.password_hash = None
        await self._account_repository.add(
            account=OAuthAccount(
                user_id=user.id, provider=provider, subject=identity.subject, created_at=now
            )
        )
        return user
