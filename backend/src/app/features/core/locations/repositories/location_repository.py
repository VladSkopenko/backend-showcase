import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.locations.models import DiningTable, Location


class LocationRepository:
    ORDERING = (Location.created_at.asc(), Location.id.asc())

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> Sequence[Location]:
        locations = await self._session.scalars(select(Location).order_by(*self.ORDERING))
        return locations.all()

    async def list_with_table_counts(self) -> Sequence[tuple[Location, int]]:
        rows = await self._session.execute(self._with_table_count().order_by(*self.ORDERING))
        return [(location, table_count) for location, table_count in rows]

    async def get_with_table_count(self, *, location_id: uuid.UUID) -> tuple[Location, int] | None:
        statement = self._with_table_count().where(Location.id == location_id)
        row = (await self._session.execute(statement)).first()
        return None if row is None else (row[0], row[1])

    @staticmethod
    def _with_table_count() -> Select[Location, int]:
        return (
            select(Location, func.count(DiningTable.id))
            .outerjoin(DiningTable, DiningTable.location_id == Location.id)
            .group_by(Location.id)
        )
