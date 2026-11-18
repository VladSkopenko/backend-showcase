import uuid
from collections.abc import Collection, Sequence
from typing import Any

from sqlalchemy import UnaryExpression, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.menu.enums import DishCategory, DishSort
from app.features.core.menu.models import Dish


class DishRepository:
    ORDERINGS: dict[DishSort, tuple[UnaryExpression[Any], ...]] = {
        DishSort.POPULAR: (Dish.popularity.desc(), Dish.id.asc()),
        DishSort.NEWEST: (Dish.created_at.desc(), Dish.id.asc()),
        DishSort.PRICE_ASC: (Dish.price_cents.asc(), Dish.id.asc()),
        DishSort.PRICE_DESC: (Dish.price_cents.desc(), Dish.id.asc()),
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> Sequence[Dish]:
        dishes = await self._session.scalars(select(Dish).order_by(Dish.slug))
        return dishes.all()

    async def get(self, *, dish_id: uuid.UUID) -> Dish | None:
        return await self._session.get(Dish, dish_id)

    async def list_by_ids(self, *, dish_ids: Collection[uuid.UUID]) -> Sequence[Dish]:
        if not dish_ids:
            return []
        dishes = await self._session.scalars(select(Dish).where(Dish.id.in_(dish_ids)))
        return dishes.all()

    async def get_page(
        self, *, category: DishCategory | None, sort: DishSort, limit: int, offset: int
    ) -> tuple[Sequence[Dish], int]:
        filters = [] if category is None else [Dish.category == category]
        total = await self._session.scalar(select(func.count()).select_from(Dish).where(*filters))
        dishes = await self._session.scalars(
            select(Dish).where(*filters).order_by(*self.ORDERINGS[sort]).limit(limit).offset(offset)
        )
        return dishes.all(), total or 0
