import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.auth.enums import OAuthProvider
from app.features.core.auth.models import OAuthAccount


class OAuthAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_subject(self, *, provider: OAuthProvider, subject: str) -> OAuthAccount | None:
        account: OAuthAccount | None = await self._session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider, OAuthAccount.subject == subject
            )
        )
        return account

    async def get_by_user(
        self, *, user_id: uuid.UUID, provider: OAuthProvider
    ) -> OAuthAccount | None:
        account: OAuthAccount | None = await self._session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user_id, OAuthAccount.provider == provider
            )
        )
        return account

    async def add(self, *, account: OAuthAccount) -> None:
        self._session.add(account)
        await self._session.flush()
