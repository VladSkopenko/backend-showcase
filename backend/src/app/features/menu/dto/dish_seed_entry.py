from dataclasses import dataclass
from pathlib import PurePath
from typing import Annotated, ClassVar

from pydantic import ConfigDict, Field

from app.features.menu.enums import DishCategory

ShortText = Annotated[str, Field(min_length=1, max_length=50)]


@dataclass(frozen=True)
class DishSeedEntry:
    # Read by pydantic when the seed validates dishes.json: a misspelt key fails the whole file.
    __pydantic_config__ = ConfigDict(extra="forbid")

    CONTENT_TYPES: ClassVar[dict[str, str]] = {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".png": "image/png",
    }

    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=100)]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1)]
    category: DishCategory
    price_cents: Annotated[int, Field(gt=0)]
    weight_grams: Annotated[int, Field(gt=0)]
    calories: Annotated[int, Field(ge=0)]
    protein: ShortText
    fats: ShortText
    carbs: ShortText
    vitamins: Annotated[str, Field(min_length=1)]
    # A bare file name next to dishes.json, never a path.
    image: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+\.(webp|jpg|png)$")]
    is_available: bool = True
    popularity: Annotated[int, Field(ge=0)] = 0

    @property
    def content_type(self) -> str:
        return self.CONTENT_TYPES[PurePath(self.image).suffix]

    @property
    def image_key(self) -> str:
        return f"dishes/{self.slug}{PurePath(self.image).suffix}"
