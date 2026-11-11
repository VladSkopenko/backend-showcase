from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.bookings.models import Guest


class GuestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, *, token_hash: str) -> Guest | None:
        guest: Guest | None = await self._session.scalar(
            select(Guest).where(Guest.token_hash == token_hash)
        )
        return guest

    async def add(self, *, guest: Guest) -> None:
        self._session.add(guest)
        await self._session.flush()
