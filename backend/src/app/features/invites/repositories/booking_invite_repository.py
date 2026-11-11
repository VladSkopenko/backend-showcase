import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.invites.models import BookingInvite


class BookingInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, *, code: str) -> BookingInvite | None:
        invite: BookingInvite | None = await self._session.scalar(
            select(BookingInvite).where(BookingInvite.code == code)
        )
        return invite

    async def get_by_booking_id(self, *, booking_id: uuid.UUID) -> BookingInvite | None:
        invite: BookingInvite | None = await self._session.scalar(
            select(BookingInvite).where(BookingInvite.booking_id == booking_id)
        )
        return invite

    async def add(self, *, invite: BookingInvite) -> None:
        self._session.add(invite)
        await self._session.flush()
