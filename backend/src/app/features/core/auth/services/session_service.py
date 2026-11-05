import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.auth.dto import IssuedSession, RefreshOutcome
from app.features.core.auth.models import RefreshToken
from app.features.core.auth.repositories import RefreshTokenRepository
from app.features.core.auth.services.access_token_codec import AccessTokenCodec
from app.features.core.auth.services.exceptions import SessionInvalidError
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class SessionService:
    def __init__(
        self, session: AsyncSession, access_token_codec: AccessTokenCodec, *, refresh_ttl_days: int
    ) -> None:
        self._user_repository = UserRepository(session)
        self._token_repository = RefreshTokenRepository(session)
        self._access_token_codec = access_token_codec
        self._refresh_ttl = timedelta(days=refresh_ttl_days)

    async def start(self, *, user: User) -> IssuedSession:
        now = clock.now()
        refresh_token = secrets.token_urlsafe(32)
        await self._token_repository.add(
            token=RefreshToken(
                user_id=user.id,
                token_hash=self._hash_token(refresh_token),
                created_at=now,
                expires_at=now + self._refresh_ttl,
            )
        )
        return IssuedSession(
            access_token=self._access_token_codec.encode(user_id=user.id),
            refresh_token=refresh_token,
        )

    async def refresh(self, *, refresh_token: str | None) -> RefreshOutcome:
        # Failures are returned, not raised: raising would roll back a reuse revocation.
        stored = await self._lock_token(refresh_token=refresh_token)
        if stored is None:
            return RefreshOutcome(error=SessionInvalidError())
        token, user = stored
        now = clock.now()
        if token.rotated_at is not None:
            await self._token_repository.revoke_all_active(user_id=user.id, now=now)
            return RefreshOutcome(error=SessionInvalidError())
        if token.revoked_at is not None or token.expires_at <= now:
            return RefreshOutcome(error=SessionInvalidError())
        token.revoked_at = now
        token.rotated_at = now
        return RefreshOutcome(session=await self.start(user=user))

    async def end(self, *, refresh_token: str | None) -> None:
        stored = await self._lock_token(refresh_token=refresh_token)
        if stored is None:
            return
        token, user = stored
        now = clock.now()
        if token.rotated_at is not None:
            await self._token_repository.revoke_all_active(user_id=user.id, now=now)
            return
        if token.revoked_at is None:
            token.revoked_at = now

    async def _lock_token(self, *, refresh_token: str | None) -> tuple[RefreshToken, User] | None:
        # The user row is locked before the token is re-read, so a concurrent rotation cannot
        # insert a new token past a mass revocation, and two refreshes of one token serialise.
        if refresh_token is None:
            return None
        token_hash = self._hash_token(refresh_token)
        token = await self._token_repository.get_by_hash(token_hash=token_hash)
        if token is None:
            return None
        user = await self._user_repository.get_by_id(user_id=token.user_id, for_update=True)
        token = await self._token_repository.get_by_hash(token_hash=token_hash, for_update=True)
        if user is None or token is None:
            return None
        return token, user

    def _hash_token(self, token: str) -> str:
        # The token has 256 random bits, so a plain SHA-256 is enough; Argon2 is for passwords.
        return hashlib.sha256(token.encode()).hexdigest()
