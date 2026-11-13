from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.menu.dto import DishSeedEntry
from app.features.core.menu.enums import DishCategory
from app.features.core.menu.repositories import DishRepository
from app.features.core.menu.services.exceptions import MenuSeedFileError

# boto3 is a dev dependency and the runtime image lacks it, so the storage type is imported only
# for type checking: importing this module must never pull boto3 in.
if TYPE_CHECKING:
    from app.infrastructure.storage import S3FileStorage


class DishSeedService:
    FILE_NAME = "dishes.json"
    ENTRIES = TypeAdapter(list[DishSeedEntry])
    DEFAULT_PREP_MINUTES = {
        DishCategory.APPETIZER: 10,
        DishCategory.MAIN_COURSE: 20,
        DishCategory.DESSERT: 10,
    }

    def __init__(self, session: AsyncSession, storage: S3FileStorage) -> None:
        self._repository = DishRepository(session)
        self._storage = storage

    @classmethod
    def load(cls, *, directory: Path) -> list[DishSeedEntry]:
        try:
            entries = cls.ENTRIES.validate_json((directory / cls.FILE_NAME).read_bytes())
        except OSError as error:
            raise MenuSeedFileError(str(error)) from error
        except ValidationError as error:
            raise MenuSeedFileError(str(error)) from error
        slugs = [entry.slug for entry in entries]
        duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        if duplicates:
            raise MenuSeedFileError(f"duplicate slugs {duplicates}")
        missing = [entry.image for entry in entries if not (directory / entry.image).is_file()]
        if missing:
            raise MenuSeedFileError(f"missing pictures {missing}")
        return entries

    async def run(self, *, directory: Path) -> int:
        entries = self.load(directory=directory)
        for entry in entries:
            self._storage.put(
                key=entry.image_key,
                content=(directory / entry.image).read_bytes(),
                content_type=entry.content_type,
            )
        await self.save(entries=entries)
        return len(entries)

    async def save(self, *, entries: list[DishSeedEntry]) -> None:
        now = clock.now()
        await self._repository.upsert_by_slug(
            rows=[
                {
                    "slug": entry.slug,
                    "name": entry.name,
                    "description": entry.description,
                    "category": entry.category,
                    "price_cents": entry.price_cents,
                    "weight_grams": entry.weight_grams,
                    "calories": entry.calories,
                    "protein": entry.protein,
                    "fats": entry.fats,
                    "carbs": entry.carbs,
                    "vitamins": entry.vitamins,
                    "is_available": entry.is_available,
                    "popularity": entry.popularity,
                    "prep_minutes": self._prep_minutes(entry),
                    "image_key": entry.image_key,
                    # The first entry is the newest, so NEWEST follows the file order.
                    "created_at": now - timedelta(minutes=position),
                    "updated_at": now,
                }
                for position, entry in enumerate(entries)
            ],
            now=now,
        )

    def _prep_minutes(self, entry: DishSeedEntry) -> int:
        if entry.prep_minutes is not None:
            return entry.prep_minutes
        return self.DEFAULT_PREP_MINUTES[entry.category]
