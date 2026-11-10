import uuid
from dataclasses import dataclass

from app.features.core.menu.enums import DishCategory


@dataclass(frozen=True)
class DishView:
    id: uuid.UUID
    name: str
    category: DishCategory
    price_cents: int
    weight_grams: int
    is_available: bool
    popularity: int
    image_url: str
    description: str
    calories: int
    protein: str
    fats: str
    carbs: str
    vitamins: str
