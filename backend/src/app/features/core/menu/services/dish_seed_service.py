from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.menu.repositories import DishRepository
from app.features.core.menu.services.exceptions import MenuSeedFileError

# boto3 is a dev dependency and the runtime image lacks it, so the storage type is imported only
# for type checking: importing this module must never pull boto3 in.
if TYPE_CHECKING:
    from app.infrastructure.storage import S3FileStorage


class DishSeedService:
    CONTENT_TYPES = {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".png": "image/png",
    }

    def __init__(self, session: AsyncSession, storage: S3FileStorage) -> None:
        self._repository = DishRepository(session)
        self._storage = storage

    async def run(self, *, directory: Path) -> int:
        pictures = [
            (dish.image_key, directory / Path(dish.image_key).name)
            for dish in await self._repository.list_all()
        ]
        if not pictures:
            raise MenuSeedFileError("no dishes in the database; run the migrations first")
        unsupported = [path.name for _, path in pictures if path.suffix not in self.CONTENT_TYPES]
        if unsupported:
            raise MenuSeedFileError(f"unsupported picture types {unsupported}")
        missing = [path.name for _, path in pictures if not path.is_file()]
        if missing:
            raise MenuSeedFileError(f"missing pictures {missing}")
        for image_key, path in pictures:
            self._storage.put(
                key=image_key,
                content=path.read_bytes(),
                content_type=self.CONTENT_TYPES[path.suffix],
            )
        return len(pictures)
