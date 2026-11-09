import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.config.settings import Settings, get_settings
from app.features.menu.enums import DishCategory
from app.main import create_app
from app.model_registry import Dish

pytestmark = pytest.mark.anyio

MENU = "/api/v1/menu/dishes"
MEDIA_BASE_URL = "https://media.example.com/n/ns/b/media/o"
START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
CARD_KEYS = {
    "id",
    "name",
    "category",
    "price_cents",
    "weight_grams",
    "is_available",
    "popularity",
    "image_url",
}
DETAIL_KEYS = CARD_KEYS | {"description", "calories", "protein", "fats", "carbs", "vitamins"}


def make_dish(slug: str, **overrides: Any) -> Dish:
    values: dict[str, Any] = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "description": f"About {slug}",
        "category": DishCategory.MAIN_COURSE,
        "price_cents": 1000,
        "weight_grams": 300,
        "calories": 450,
        "protein": "18-20g",
        "fats": "10g",
        "carbs": "40g",
        "vitamins": "A, C",
        "is_available": True,
        "popularity": 0,
        "image_key": f"dishes/{slug}.webp",
        "created_at": START,
    }
    values.update(overrides)
    return Dish(**values)


@pytest.fixture(autouse=True)
async def empty_menu(connection: AsyncConnection) -> None:
    # Migration 0007 fills the menu; these tests build their own dishes.
    await connection.execute(text("DELETE FROM dishes"))


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # A trailing slash in the setting must not double the slash in image_url.
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", f"{MEDIA_BASE_URL}/")
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
def add_dishes(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    async def add(*dishes: Dish) -> list[Dish]:
        async with session_factory() as session:
            session.add_all(dishes)
            await session.commit()
        return list(dishes)

    return add


async def list_dishes(client: httpx2.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(MENU, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_default_list_is_the_first_page_by_popularity(
    client: httpx2.AsyncClient, add_dishes: Any
) -> None:
    await add_dishes(*(make_dish(f"dish-{n:02}", popularity=n) for n in range(21)))

    body = await list_dishes(client)

    assert body["total"] == 21
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["popularity"] for item in body["items"]] == list(range(20, 0, -1))


async def test_list_item_is_the_card_with_popularity(
    client: httpx2.AsyncClient, add_dishes: Any
) -> None:
    [dish] = await add_dishes(
        make_dish("tomato-soup", category=DishCategory.APPETIZER, price_cents=850, popularity=7)
    )

    [item] = (await list_dishes(client))["items"]

    assert set(item) == CARD_KEYS
    assert item == {
        "id": str(dish.id),
        "name": "Tomato Soup",
        "category": "APPETIZER",
        "price_cents": 850,
        "weight_grams": 300,
        "is_available": True,
        "popularity": 7,
        "image_url": f"{MEDIA_BASE_URL}/dishes/tomato-soup.webp",
    }


async def test_category_filter_lists_and_counts_only_that_category(
    client: httpx2.AsyncClient, add_dishes: Any
) -> None:
    await add_dishes(
        make_dish("cake", category=DishCategory.DESSERT),
        make_dish("pie", category=DishCategory.DESSERT),
        make_dish("steak", category=DishCategory.MAIN_COURSE),
        make_dish("salad", category=DishCategory.APPETIZER),
    )

    body = await list_dishes(client, category="DESSERT")

    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"Cake", "Pie"}
    assert {item["category"] for item in body["items"]} == {"DESSERT"}


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("POPULAR", ["b-popular", "tie-1", "tie-2", "a-cheap"]),
        ("NEWEST", ["a-cheap", "tie-1", "tie-2", "b-popular"]),
        ("PRICE_ASC", ["a-cheap", "tie-1", "tie-2", "b-popular"]),
        ("PRICE_DESC", ["b-popular", "tie-1", "tie-2", "a-cheap"]),
    ],
)
async def test_each_sort_orders_and_breaks_ties_by_id(
    client: httpx2.AsyncClient, add_dishes: Any, sort: str, expected: list[str]
) -> None:
    first_tie, second_tie = sorted([uuid.uuid4(), uuid.uuid4()])
    dishes = await add_dishes(
        make_dish("a-cheap", price_cents=100, popularity=1, created_at=START),
        make_dish(
            "b-popular", price_cents=900, popularity=9, created_at=START - timedelta(hours=2)
        ),
        # The ties share every sort value; inserted in reverse to prove the order comes from id.
        make_dish(
            "tie-2",
            id=second_tie,
            price_cents=500,
            popularity=5,
            created_at=START - timedelta(hours=1),
        ),
        make_dish(
            "tie-1",
            id=first_tie,
            price_cents=500,
            popularity=5,
            created_at=START - timedelta(hours=1),
        ),
    )
    ids_by_slug = {dish.slug: str(dish.id) for dish in dishes}

    body = await list_dishes(client, sort=sort)

    assert [item["id"] for item in body["items"]] == [ids_by_slug[slug] for slug in expected]


async def test_limit_and_offset_select_a_page_with_the_same_total(
    client: httpx2.AsyncClient, add_dishes: Any
) -> None:
    await add_dishes(*(make_dish(f"dish-{n}", popularity=n) for n in range(5)))

    body = await list_dishes(client, limit=2, offset=2)

    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert [item["popularity"] for item in body["items"]] == [2, 1]


async def test_offset_past_the_end_is_an_empty_page_with_the_real_total(
    client: httpx2.AsyncClient, add_dishes: Any
) -> None:
    await add_dishes(make_dish("one"), make_dish("two"))

    body = await list_dishes(client, offset=2)

    assert body["items"] == []
    assert body["total"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"offset": 2**63},
        {"sort": "CHEAPEST"},
        {"category": "SOUP"},
    ],
)
async def test_bad_list_params_are_422(client: httpx2.AsyncClient, params: dict[str, Any]) -> None:
    response = await client.get(MENU, params=params)

    assert response.status_code == 422


async def test_sold_out_dishes_are_listed(client: httpx2.AsyncClient, add_dishes: Any) -> None:
    await add_dishes(make_dish("gone", is_available=False))

    [item] = (await list_dishes(client))["items"]

    assert item["is_available"] is False


async def test_item_returns_the_full_dish(client: httpx2.AsyncClient, add_dishes: Any) -> None:
    [dish] = await add_dishes(make_dish("lava-cake", category=DishCategory.DESSERT))

    response = await client.get(f"{MENU}/{dish.id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(dish.id),
        "name": "Lava Cake",
        "category": "DESSERT",
        "price_cents": 1000,
        "weight_grams": 300,
        "is_available": True,
        "popularity": 0,
        "image_url": f"{MEDIA_BASE_URL}/dishes/lava-cake.webp",
        "description": "About lava-cake",
        "calories": 450,
        "protein": "18-20g",
        "fats": "10g",
        "carbs": "40g",
        "vitamins": "A, C",
    }
    assert set(response.json()) == DETAIL_KEYS


async def test_unknown_item_is_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"{MENU}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "DISH_NOT_FOUND"


async def test_menu_needs_no_session(client: httpx2.AsyncClient, add_dishes: Any) -> None:
    [dish] = await add_dishes(make_dish("bread"))
    client.cookies.clear()

    assert (await client.get(MENU)).status_code == 200
    assert (await client.get(f"{MENU}/{dish.id}")).status_code == 200
