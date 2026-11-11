import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.locations.models import DiningTable, Location
from app.features.core.locations.repositories import LocationRepository


class BookableTableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_fitting(
        self, *, min_capacity: int, max_capacity: int, location_id: uuid.UUID | None
    ) -> Sequence[DiningTable]:
        filters = [] if location_id is None else [DiningTable.location_id == location_id]
        tables = await self._session.scalars(
            select(DiningTable)
            .join(Location, Location.id == DiningTable.location_id)
            .where(DiningTable.capacity.between(min_capacity, max_capacity), *filters)
            # By length first, so "Table 2" comes before "Table 10".
            .order_by(
                *LocationRepository.ORDERING,
                func.char_length(DiningTable.label),
                DiningTable.label,
            )
        )
        return tables.all()

    async def get(self, *, table_id: uuid.UUID, for_update: bool = False) -> DiningTable | None:
        statement = select(DiningTable).where(DiningTable.id == table_id)
        if for_update:
            statement = statement.with_for_update()
        table: DiningTable | None = await self._session.scalar(statement)
        return table
