import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.auth.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(
        self, *, token_hash: str, for_update: bool = False
    ) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            # FOR UPDATE alone keeps the stale object already in the identity map; the re-read
            # after locking must overwrite it with the row as it is now.
            statement = statement.with_for_update().execution_options(populate_existing=True)
        token: RefreshToken | None = await self._session.scalar(statement)
        return token

    async def add(self, *, token: RefreshToken) -> None:
        self._session.add(token)
        await self._session.flush()

    async def revoke_all_active(self, *, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(revoked_at=now)
        )
