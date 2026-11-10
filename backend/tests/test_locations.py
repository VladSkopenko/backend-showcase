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
from app.main import create_app
from app.model_registry import DiningTable, Location

pytestmark = pytest.mark.anyio

LOCATIONS = "/api/v1/locations"
MEDIA_BASE_URL = "https://media.example.com/n/ns/b/media/o"
START = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
CARD_KEYS = {"id", "address", "image_url", "table_count"}


def make_location(slug: str, *, minutes: int = 0) -> Location:
    return Location(
        slug=slug,
        address=slug.replace("-", " ").title(),
        description=f"About {slug}",
        image_key=f"locations/{slug}.jpg",
        created_at=START + timedelta(minutes=minutes),
    )


@pytest.fixture(autouse=True)
async def no_locations(connection: AsyncConnection) -> None:
    await connection.execute(text("DELETE FROM locations"))


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
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
async def two_locations(session_factory: async_sessionmaker[AsyncSession]) -> list[Location]:
    with_tables = make_location("old-town-square")
    without_tables = make_location("river-embankment", minutes=1)
    async with session_factory() as session:
        session.add_all([without_tables, with_tables])
        await session.flush()
        session.add_all(
            DiningTable(location_id=with_tables.id, label=f"Table {n}", capacity=4)
            for n in range(1, 4)
        )
        await session.commit()
    return [with_tables, without_tables]


async def test_list_is_every_location_in_created_order_with_its_table_count(
    client: httpx2.AsyncClient, two_locations: list[Location]
) -> None:
    with_tables, without_tables = two_locations

    response = await client.get(LOCATIONS)

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": str(with_tables.id),
            "address": "Old Town Square",
            "image_url": f"{MEDIA_BASE_URL}/locations/old-town-square.jpg",
            "table_count": 3,
        },
        {
            "id": str(without_tables.id),
            "address": "River Embankment",
            "image_url": f"{MEDIA_BASE_URL}/locations/river-embankment.jpg",
            "table_count": 0,
        },
    ]


async def test_empty_list_is_an_empty_array(client: httpx2.AsyncClient) -> None:
    response = await client.get(LOCATIONS)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(("position", "table_count"), [(0, 3), (1, 0)])
async def test_item_adds_the_description_to_the_list_fields(
    client: httpx2.AsyncClient, two_locations: list[Location], position: int, table_count: int
) -> None:
    location = two_locations[position]

    response = await client.get(f"{LOCATIONS}/{location.id}")

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == CARD_KEYS | {"description"}
    assert body["id"] == str(location.id)
    assert body["table_count"] == table_count
    assert body["description"] == f"About {location.slug}"
    assert body["image_url"] == f"{MEDIA_BASE_URL}/locations/{location.slug}.jpg"


async def test_unknown_item_is_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"{LOCATIONS}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "LOCATION_NOT_FOUND"
