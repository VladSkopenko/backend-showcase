from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.locations.repositories import LocationRepository
from app.features.core.locations.services.exceptions import LocationPhotoSeedError

if TYPE_CHECKING:
    from app.infrastructure.storage import S3FileStorage


class LocationPhotoSeedService:
    CONTENT_TYPE = "image/jpeg"

    def __init__(self, session: AsyncSession, storage: S3FileStorage) -> None:
        self._repository = LocationRepository(session)
        self._storage = storage

    async def run(self, *, directory: Path) -> int:
        photos = [
            (location, directory / Path(location.image_key).name)
            for location in await self._repository.list_all()
        ]
        missing = [location.slug for location, path in photos if not path.is_file()]
        if missing:
            raise LocationPhotoSeedError(missing)
        for location, path in photos:
            self._storage.put(
                key=location.image_key, content=path.read_bytes(), content_type=self.CONTENT_TYPE
            )
        return len(photos)
