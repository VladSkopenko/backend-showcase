import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.core.menu.enums import DishCategory
from app.model_registry import Booking, Dish, User
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    START,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    add_guest,
    add_participant,
    at,
)

NOON = at(TOMORROW, 12)


@dataclass
class Menu:
    soup: Dish
    steak: Dish
    cake: Dish
    gone: Dish


@dataclass
class Party:
    booking: Booking
    alex: str
    maria: str
    bea: str


def make_dish(
    slug: str, category: DishCategory, price_cents: int, prep_minutes: int, is_available: bool
) -> Dish:
    return Dish(
        slug=slug,
        name=slug.replace("-", " ").title(),
        description=f"About {slug}",
        category=category,
        price_cents=price_cents,
        weight_grams=300,
        calories=450,
        protein="18g",
        fats="10g",
        carbs="40g",
        vitamins="A, C",
        is_available=is_available,
        popularity=0,
        prep_minutes=prep_minutes,
        image_key=f"dishes/{slug}.webp",
        created_at=START,
    )


async def add_party(
    session_factory: async_sessionmaker[AsyncSession],
    venue: Venue,
    users: dict[str, User],
    *,
    starts_at: datetime = NOON,
) -> Party:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=starts_at, party_size=3
    )
    other = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=starts_at, party_size=2
    )
    tokens = {}
    for name, booking_id in (("Alex", booking.id), ("Maria", booking.id), ("Bea", other.id)):
        token = f"{name.lower()}-{uuid.uuid4()}"
        guest = await add_guest(session_factory, name=name, token=token)
        await add_participant(session_factory, booking_id=booking_id, guest=guest)
        tokens[name] = token
    return Party(booking=booking, alex=tokens["Alex"], maria=tokens["Maria"], bea=tokens["Bea"])


def cart_url(booking: Booking) -> str:
    return f"{BOOKINGS}/{booking.id}/cart"


def item_url(booking: Booking, dish_id: uuid.UUID | str) -> str:
    return f"{BOOKINGS}/{booking.id}/cart/items/{dish_id}"


async def put_item(
    client: httpx2.AsyncClient,
    booking: Booking,
    dish_id: uuid.UUID | str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    return await client.put(item_url(booking, dish_id), json=body, headers=headers)


async def remove_item(
    client: httpx2.AsyncClient,
    booking: Booking,
    dish_id: uuid.UUID | str,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    return await client.delete(item_url(booking, dish_id), headers=headers)


async def submit(
    client: httpx2.AsyncClient, booking: Booking, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return await client.post(f"{cart_url(booking)}/submit", headers=headers)


async def get_cart(
    client: httpx2.AsyncClient, booking: Booking, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return await client.get(cart_url(booking), headers=headers)


async def my_preorder(
    client: httpx2.AsyncClient, booking: Booking, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return await client.get(f"{BOOKINGS}/{booking.id}/my-pre-order", headers=headers)


async def fill(
    client: httpx2.AsyncClient,
    fake_clock: FakeClock,
    booking: Booking,
    lines: list[tuple[Dish, int]],
    headers: dict[str, str] | None = None,
) -> None:
    for dish, quantity in lines:
        fake_clock.advance(seconds=1)
        response = await put_item(client, booking, dish.id, {"quantity": quantity}, headers)
        assert response.status_code == 200, response.text
