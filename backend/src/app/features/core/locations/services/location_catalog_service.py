import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.locations.dto import LocationView
from app.features.core.locations.models import Location
from app.features.core.locations.repositories import LocationRepository
from app.features.core.locations.services.exceptions import LocationNotFoundError


class LocationCatalogService:
    def __init__(self, session: AsyncSession, *, public_base_url: str) -> None:
        self._repository = LocationRepository(session)
        self._public_base_url = public_base_url

    async def list_all(self) -> list[LocationView]:
        rows = await self._repository.list_with_table_counts()
        return [self._to_view(location, table_count) for location, table_count in rows]

    async def get(self, *, location_id: uuid.UUID) -> LocationView:
        row = await self._repository.get_with_table_count(location_id=location_id)
        if row is None:
            raise LocationNotFoundError()
        return self._to_view(*row)

    def _to_view(self, location: Location, table_count: int) -> LocationView:
        return LocationView(
            id=location.id,
            address=location.address,
            image_url=f"{self._public_base_url}/{location.image_key}",
            table_count=table_count,
            description=location.description,
        )
