from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.email_addresses import normalize_email
from app.features.core.users.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, *, email: str, for_update: bool = False) -> User | None:
        statement = select(User).where(User.email == normalize_email(email))
        if for_update:
            statement = statement.with_for_update()
        user: User | None = await self._session.scalar(statement)
        return user

    async def add(self, *, user: User) -> None:
        self._session.add(user)
        await self._session.flush()
