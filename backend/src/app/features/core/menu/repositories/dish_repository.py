import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import UnaryExpression, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.menu.enums import DishCategory, DishSort
from app.features.core.menu.models import Dish


class DishRepository:
    CONTENT_COLUMNS = (
        "name",
        "description",
        "category",
        "price_cents",
        "weight_grams",
        "calories",
        "protein",
        "fats",
        "carbs",
        "vitamins",
        "is_available",
        "image_key",
    )
    ORDERINGS: dict[DishSort, tuple[UnaryExpression[Any], ...]] = {
        DishSort.POPULAR: (Dish.popularity.desc(), Dish.id.asc()),
        DishSort.NEWEST: (Dish.created_at.desc(), Dish.id.asc()),
        DishSort.PRICE_ASC: (Dish.price_cents.asc(), Dish.id.asc()),
        DishSort.PRICE_DESC: (Dish.price_cents.desc(), Dish.id.asc()),
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, dish_id: uuid.UUID) -> Dish | None:
        return await self._session.get(Dish, dish_id)

    async def get_page(
        self, *, category: DishCategory | None, sort: DishSort, limit: int, offset: int
    ) -> tuple[Sequence[Dish], int]:
        filters = [] if category is None else [Dish.category == category]
        total = await self._session.scalar(select(func.count()).select_from(Dish).where(*filters))
        dishes = await self._session.scalars(
            select(Dish).where(*filters).order_by(*self.ORDERINGS[sort]).limit(limit).offset(offset)
        )
        return dishes.all(), total or 0

    async def upsert_by_slug(self, *, rows: Sequence[dict[str, Any]], now: datetime) -> None:
        if not rows:
            return
        statement = insert(Dish).values(list(rows))
        excluded = statement.excluded
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[Dish.slug],
                set_={
                    **{column: excluded[column] for column in self.CONTENT_COLUMNS},
                    "updated_at": now,
                },
                # Rows whose content did not change keep their updated_at.
                where=or_(
                    *(
                        getattr(Dish, column).is_distinct_from(excluded[column])
                        for column in self.CONTENT_COLUMNS
                    )
                ),
            )
        )
