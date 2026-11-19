import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import timedelta

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from support.bookings import (
    PASSWORD,
    START,
    TOMORROW,
    FakeClock,
    assert_error,
    at,
    book,
    edit,
    sign_in,
)

from app.common import database
from app.config.settings import Settings, get_settings
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.main import create_app
from app.model_registry import Booking, DiningTable, Location, User

pytestmark = pytest.mark.anyio

RACE_TIMEOUT_SECONDS = 20


@dataclass
class World:
    sessionmaker: async_sessionmaker[AsyncSession]
    location: Location
    first: DiningTable
    second: DiningTable
    ada: User
    grace: User


@pytest.fixture
async def world(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, fake_clock: FakeClock
) -> AsyncIterator[World]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "get_sessionmaker", lambda: sessionmaker)
    password_hash = await PasswordHasher().hash(password=PASSWORD)
    run = uuid.uuid4().hex
    location = Location(
        slug=f"race-{run}",
        address="Race Street",
        description="Race",
        image_key=f"locations/race-{run}.jpg",
    )
    ada, grace = (
        User(
            first_name=name.title(),
            last_name="Racer",
            email=f"{name}-{run}@example.com",
            password_hash=password_hash,
            email_verified_at=START - timedelta(days=1),
        )
        for name in ("ada", "grace")
    )
    async with sessionmaker() as session:
        session.add_all([location, ada, grace])
        await session.flush()
        first = DiningTable(location_id=location.id, label="Table 1", capacity=4)
        second = DiningTable(location_id=location.id, label="Table 2", capacity=4)
        session.add_all([first, second])
        await session.commit()
    try:
        yield World(sessionmaker, location, first, second, ada, grace)
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(delete(User).where(User.id.in_([ada.id, grace.id])))
            await cleanup.execute(delete(Location).where(Location.id == location.id))


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def clients(app: FastAPI) -> AsyncIterator[tuple[httpx2.AsyncClient, httpx2.AsyncClient]]:
    transport = httpx2.ASGITransport(app=app)
    async with (
        httpx2.AsyncClient(transport=transport, base_url="https://test") as first,
        httpx2.AsyncClient(transport=transport, base_url="https://test") as second,
    ):
        yield first, second


async def race(
    first: Awaitable[httpx2.Response], second: Awaitable[httpx2.Response]
) -> list[httpx2.Response]:
    responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=RACE_TIMEOUT_SECONDS)
    return sorted(responses, key=lambda response: response.status_code)


async def bookings_where(world: World, *conditions: ColumnElement[bool]) -> int:
    async with world.sessionmaker() as session:
        count = await session.scalar(select(func.count()).select_from(Booking).where(*conditions))
    return int(count or 0)


async def test_two_guests_booking_one_table_for_one_slot_at_once_leave_one_booking(
    world: World, clients: tuple[httpx2.AsyncClient, httpx2.AsyncClient]
) -> None:
    ada, grace = clients
    await sign_in(ada, world.ada.email)
    await sign_in(grace, world.grace.email)

    won, lost = await race(
        book(ada, world.first.id, at(TOMORROW, 12)),
        book(grace, world.first.id, at(TOMORROW, 12)),
    )

    assert won.status_code == 201, won.text
    assert_error(lost, 409, "SLOT_UNAVAILABLE")
    assert await bookings_where(world, Booking.table_id == world.first.id) == 1


async def test_one_guest_booking_two_tables_for_one_slot_at_once_keeps_one_booking(
    world: World, clients: tuple[httpx2.AsyncClient, httpx2.AsyncClient]
) -> None:
    ada, _ = clients
    await sign_in(ada, world.ada.email)

    won, lost = await race(
        book(ada, world.first.id, at(TOMORROW, 12)),
        book(ada, world.second.id, at(TOMORROW, 12, 30)),
    )

    assert won.status_code == 201, won.text
    assert_error(lost, 409, "OVERLAPPING_BOOKING")
    assert await bookings_where(world, Booking.user_id == world.ada.id) == 1


async def test_two_guests_moving_onto_one_slot_of_one_table_at_once_leave_one_there(
    world: World, clients: tuple[httpx2.AsyncClient, httpx2.AsyncClient]
) -> None:
    ada, grace = clients
    await sign_in(ada, world.ada.email)
    await sign_in(grace, world.grace.email)
    early = (await book(ada, world.first.id, at(TOMORROW, 12))).json()
    late = (await book(grace, world.first.id, at(TOMORROW, 16))).json()

    won, lost = await race(
        edit(ada, early["id"], at(TOMORROW, 14)),
        edit(grace, late["id"], at(TOMORROW, 14)),
    )

    assert won.status_code == 200, won.text
    assert_error(lost, 409, "SLOT_UNAVAILABLE")
    assert (
        await bookings_where(
            world,
            Booking.table_id == world.first.id,
            Booking.starts_at == at(TOMORROW, 14),
        )
        == 1
    )


async def test_one_guest_moving_two_bookings_onto_one_slot_at_once_keeps_them_apart(
    world: World, clients: tuple[httpx2.AsyncClient, httpx2.AsyncClient]
) -> None:
    ada, _ = clients
    await sign_in(ada, world.ada.email)
    early = (await book(ada, world.first.id, at(TOMORROW, 12))).json()
    late = (await book(ada, world.second.id, at(TOMORROW, 16))).json()

    won, lost = await race(
        edit(ada, early["id"], at(TOMORROW, 14)),
        edit(ada, late["id"], at(TOMORROW, 14)),
    )

    assert won.status_code == 200, won.text
    assert_error(lost, 409, "OVERLAPPING_BOOKING")
    assert (
        await bookings_where(
            world, Booking.user_id == world.ada.id, Booking.starts_at == at(TOMORROW, 14)
        )
        == 1
    )
