import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.menu.dto import DishPage, DishView
from app.features.core.menu.enums import DishCategory, DishSort
from app.features.core.menu.models import Dish
from app.features.core.menu.repositories import DishRepository
from app.features.core.menu.services.exceptions import DishNotFoundError


class DishCatalogService:
    def __init__(self, session: AsyncSession, *, public_base_url: str) -> None:
        self._repository = DishRepository(session)
        self._public_base_url = public_base_url

    async def list_page(
        self, *, category: DishCategory | None, sort: DishSort, limit: int, offset: int
    ) -> DishPage:
        dishes, total = await self._repository.get_page(
            category=category, sort=sort, limit=limit, offset=offset
        )
        return DishPage(
            items=[self._to_view(dish) for dish in dishes], total=total, limit=limit, offset=offset
        )

    async def get(self, *, dish_id: uuid.UUID) -> DishView:
        dish = await self._repository.get(dish_id=dish_id)
        if dish is None:
            raise DishNotFoundError()
        return self._to_view(dish)

    def _to_view(self, dish: Dish) -> DishView:
        return DishView(
            id=dish.id,
            name=dish.name,
            category=dish.category,
            price_cents=dish.price_cents,
            weight_grams=dish.weight_grams,
            is_available=dish.is_available,
            popularity=dish.popularity,
            image_url=f"{self._public_base_url}/{dish.image_key}",
            description=dish.description,
            calories=dish.calories,
            protein=dish.protein,
            fats=dish.fats,
            carbs=dish.carbs,
            vitamins=dish.vitamins,
        )
