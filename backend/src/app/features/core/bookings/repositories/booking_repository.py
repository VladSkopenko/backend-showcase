import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.models import Booking
from app.features.core.locations.models import DiningTable


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, booking: Booking) -> None:
        self._session.add(booking)
        await self._session.flush()

    async def list_confirmed_overlapping(
        self, *, table_ids: Sequence[uuid.UUID], starts_at: datetime, ends_at: datetime
    ) -> Sequence[Booking]:
        bookings = await self._session.scalars(
            select(Booking).where(
                Booking.table_id.in_(table_ids),
                *self._confirmed_overlapping(starts_at=starts_at, ends_at=ends_at),
            )
        )
        return bookings.all()

    async def table_has_confirmed_overlap(
        self, *, table_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> bool:
        return await self._exists(
            Booking.table_id == table_id,
            *self._confirmed_overlapping(starts_at=starts_at, ends_at=ends_at),
        )

    async def user_has_confirmed_overlap(
        self, *, user_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> bool:
        return await self._exists(
            Booking.user_id == user_id,
            *self._confirmed_overlapping(starts_at=starts_at, ends_at=ends_at),
        )

    async def list_for_user(self, *, user_id: uuid.UUID) -> Sequence[tuple[Booking, DiningTable]]:
        rows = await self._session.execute(
            select(Booking, DiningTable)
            .join(DiningTable, DiningTable.id == Booking.table_id)
            .where(Booking.user_id == user_id)
            .order_by(Booking.starts_at.desc(), Booking.id.asc())
        )
        return [(booking, table) for booking, table in rows]

    async def get_for_user(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID, for_update: bool = False
    ) -> tuple[Booking, DiningTable] | None:
        statement = (
            select(Booking, DiningTable)
            .join(DiningTable, DiningTable.id == Booking.table_id)
            .where(Booking.id == booking_id, Booking.user_id == user_id)
        )
        if for_update:
            statement = statement.with_for_update(of=Booking)
        row = (await self._session.execute(statement)).first()
        return None if row is None else (row[0], row[1])

    async def flush(self) -> None:
        await self._session.flush()

    async def _exists(self, *conditions: ColumnElement[bool]) -> bool:
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    @staticmethod
    def _confirmed_overlapping(
        *, starts_at: datetime, ends_at: datetime
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at < ends_at,
            Booking.ends_at > starts_at,
        )
