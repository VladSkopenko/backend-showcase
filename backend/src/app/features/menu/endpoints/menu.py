import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.features.menu.endpoints.dependencies import DishCatalogServiceDep
from app.features.menu.endpoints.openapi_tags import MenuOpenApiTags
from app.features.menu.enums import DishCategory, DishSort
from app.features.menu.schemas import DishPageResponse, DishResponse

router = APIRouter(prefix="/menu", tags=[MenuOpenApiTags.MENU])


@router.get(
    "/dishes",
    response_model=DishPageResponse,
    description=(
        "Lists dishes as menu cards, sold-out ones included, optionally of one category. "
        "Sorted by popularity, newest, or price; ties break by id, so pages are stable. "
        "`limit` is 20 by default and at most 50."
    ),
)
async def list_dishes(
    catalog: DishCatalogServiceDep,
    category: DishCategory | None = None,
    sort: DishSort = DishSort.POPULAR,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    # Bounded by PostgreSQL bigint: a larger offset overflows in asyncpg and would be a 500.
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> DishPageResponse:
    page = await catalog.list_page(category=category, sort=sort, limit=limit, offset=offset)
    return DishPageResponse.model_validate(page)


@router.get(
    "/dishes/{dish_id}",
    response_model=DishResponse,
    description="Returns one dish with its description and nutrition facts; 404 if unknown.",
)
async def get_dish(dish_id: uuid.UUID, catalog: DishCatalogServiceDep) -> DishResponse:
    return DishResponse.model_validate(await catalog.get(dish_id=dish_id))
