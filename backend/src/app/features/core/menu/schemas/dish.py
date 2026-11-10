import uuid

from pydantic import BaseModel, ConfigDict

from app.features.core.menu.enums import DishCategory


class DishCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: DishCategory
    price_cents: int
    weight_grams: int
    is_available: bool
    popularity: int
    image_url: str


class DishResponse(DishCardResponse):
    description: str
    calories: int
    protein: str
    fats: str
    carbs: str
    vitamins: str


class DishPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[DishCardResponse]
    total: int
    limit: int
    offset: int
