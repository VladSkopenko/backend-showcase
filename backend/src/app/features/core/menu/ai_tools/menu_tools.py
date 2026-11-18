import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai_tools import AiToolContext, invalid_arguments, tool_result, usd
from app.features.core.menu.ai_tools.arguments import GetDishArguments, ListMenuArguments
from app.features.core.menu.dto import DishView
from app.features.core.menu.enums import DishCategory, DishSort
from app.features.core.menu.services.dish_catalog_service import DishCatalogService


class MenuTools:
    LIST_LIMIT = 50

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    def build(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                coroutine=self._list_menu,
                name="list_menu",
                description=(
                    "Lists the restaurant's menu, the most popular dishes first, sold-out ones "
                    "included: name, category, price in USD, availability, weight, calories and "
                    "preparation time per dish. Filter by category or omit it for the whole menu. "
                    f"At most {self.LIST_LIMIT} dishes are listed; `total` counts every dish "
                    "that matches."
                ),
                args_schema=ListMenuArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._get_dish,
                name="get_dish",
                description=(
                    "Returns one dish with its description and nutrition facts (protein, fats, "
                    "carbs, vitamins) by the id list_menu returned."
                ),
                args_schema=GetDishArguments,
                handle_validation_error=invalid_arguments,
            ),
        ]

    async def _list_menu(self, category: DishCategory | None = None) -> str:
        async with self._context.sessionmaker() as session:
            page = await self._catalog(session).list_page(
                category=category, sort=DishSort.POPULAR, limit=self.LIST_LIMIT, offset=0
            )
        return tool_result(
            {"total": page.total, "dishes": [self._card(dish) for dish in page.items]}
        )

    async def _get_dish(self, dish_id: uuid.UUID) -> str:
        async with self._context.sessionmaker() as session:
            dish = await self._catalog(session).get(dish_id=dish_id)
        return tool_result(
            {
                **self._card(dish),
                "description": dish.description,
                "protein": dish.protein,
                "fats": dish.fats,
                "carbs": dish.carbs,
                "vitamins": dish.vitamins,
            }
        )

    def _catalog(self, session: AsyncSession) -> DishCatalogService:
        return DishCatalogService(session, public_base_url=self._context.public_base_url)

    @staticmethod
    def _card(dish: DishView) -> dict[str, Any]:
        return {
            "id": str(dish.id),
            "name": dish.name,
            "category": dish.category.value,
            "price": usd(dish.price_cents),
            "is_available": dish.is_available,
            "weight_grams": dish.weight_grams,
            "calories": dish.calories,
            "prep_minutes": dish.prep_minutes,
        }
