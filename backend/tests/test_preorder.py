import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    MEDIA_BASE_URL,
    START,
    TODAY,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    add_guest,
    add_participant,
    as_guest,
    assert_error,
    at,
    cancel,
    sign_in,
)

from app.config.settings import PreorderSettings, Settings, get_settings
from app.features.core.bookings.enums import BookingStatus
from app.features.core.menu.enums import DishCategory
from app.main import create_app
from app.model_registry import Booking, Dish, PreorderItem, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

NOON = at(TOMORROW, 12)
NO_ONIONS = "No onions please"


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


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


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


@pytest.fixture
async def menu(session_factory: async_sessionmaker[AsyncSession]) -> Menu:
    menu = Menu(
        soup=make_dish("test-soup", DishCategory.APPETIZER, 850, 10, True),
        steak=make_dish("test-steak", DishCategory.MAIN_COURSE, 2400, 25, True),
        cake=make_dish("test-cake", DishCategory.DESSERT, 650, 15, True),
        gone=make_dish("test-gone", DishCategory.MAIN_COURSE, 1800, 20, False),
    )
    async with session_factory() as session:
        session.add_all([menu.soup, menu.steak, menu.cake, menu.gone])
        await session.commit()
    return menu


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


@pytest.fixture
async def party(
    session_factory: async_sessionmaker[AsyncSession], venue: Venue, users: dict[str, User]
) -> Party:
    return await add_party(session_factory, venue, users)


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


def dish_body(dish: Dish, *, is_available: bool | None = None) -> dict[str, Any]:
    return {
        "id": str(dish.id),
        "name": dish.name,
        "price_cents": dish.price_cents,
        "image_url": f"{MEDIA_BASE_URL}/{dish.image_key}",
        "is_available": dish.is_available if is_available is None else is_available,
        "prep_minutes": dish.prep_minutes,
    }


def lines_of(body: dict[str, Any]) -> list[tuple[str, int, str | None, int]]:
    return [
        (item["dish"]["name"], item["quantity"], item["note"], item["line_total_cents"])
        for item in body["items"]
    ]


async def stored_items(
    connection: AsyncConnection,
) -> list[tuple[uuid.UUID, uuid.UUID, int, str | None, str, uuid.UUID | None]]:
    rows = await connection.execute(
        select(
            PreorderItem.participant_id,
            PreorderItem.dish_id,
            PreorderItem.quantity,
            PreorderItem.note,
            PreorderItem.state,
            PreorderItem.submission_id,
        ).order_by(PreorderItem.created_at, PreorderItem.id)
    )
    return [(row[0], row[1], row[2], row[3], row[4].value, row[5]) for row in rows]


async def make_unavailable(session_factory: async_sessionmaker[AsyncSession], dish: Dish) -> None:
    async with session_factory() as session:
        await session.execute(update(Dish).where(Dish.id == dish.id).values(is_available=False))
        await session.commit()


async def test_a_guest_adds_a_dish_with_a_note(
    client: httpx2.AsyncClient, party: Party, menu: Menu
) -> None:
    response = await put_item(
        client,
        party.booking,
        menu.soup.id,
        {"quantity": 1, "note": f"  {NO_ONIONS}  "},
        as_guest(party.alex),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    [item] = body["items"]
    assert body == {
        "items": [
            {
                "id": item["id"],
                "dish": dish_body(menu.soup),
                "quantity": 1,
                "note": NO_ONIONS,
                "line_total_cents": 850,
            }
        ],
        "total_cents": 850,
    }
    assert (await get_cart(client, party.booking, as_guest(party.alex))).json() == body


async def test_setting_a_dish_again_replaces_its_line_and_keeps_its_creation_time(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    connection: AsyncConnection,
) -> None:
    guest = as_guest(party.alex)
    first = await put_item(
        client, party.booking, menu.soup.id, {"quantity": 1, "note": NO_ONIONS}, guest
    )
    fake_clock.advance(minutes=5)

    response = await put_item(client, party.booking, menu.soup.id, {"quantity": 3}, guest)

    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    assert item["id"] == first.json()["items"][0]["id"]
    assert lines_of(response.json()) == [("Test Soup", 3, None, 2550)]
    assert response.json()["total_cents"] == 2550
    created_at, updated_at = (
        await connection.execute(select(PreorderItem.created_at, PreorderItem.updated_at))
    ).one()
    assert created_at == START
    assert updated_at == START + timedelta(minutes=5)


@pytest.mark.parametrize("note", ["", "   "])
async def test_a_blank_note_means_none(
    client: httpx2.AsyncClient, party: Party, menu: Menu, note: str
) -> None:
    response = await put_item(
        client, party.booking, menu.soup.id, {"quantity": 1, "note": note}, as_guest(party.alex)
    )

    assert response.status_code == 200, response.text
    assert lines_of(response.json()) == [("Test Soup", 1, None, 850)]


async def test_a_cart_lists_lines_by_the_time_they_were_added(
    client: httpx2.AsyncClient, party: Party, menu: Menu, fake_clock: FakeClock
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 2), (menu.soup, 1)], guest)
    fake_clock.advance(seconds=1)
    await put_item(client, party.booking, menu.steak.id, {"quantity": 1}, guest)

    response = await get_cart(client, party.booking, guest)

    assert lines_of(response.json()) == [("Test Steak", 1, None, 2400), ("Test Soup", 1, None, 850)]
    assert response.json()["total_cents"] == 3250


async def test_removing_a_dish_empties_its_line(
    client: httpx2.AsyncClient, party: Party, menu: Menu, connection: AsyncConnection
) -> None:
    guest = as_guest(party.alex)
    await put_item(client, party.booking, menu.soup.id, {"quantity": 2}, guest)

    response = await remove_item(client, party.booking, menu.soup.id, guest)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total_cents": 0}
    assert await stored_items(connection) == []


async def test_removing_a_dish_that_is_not_in_the_draft_is_not_found(
    client: httpx2.AsyncClient, party: Party, menu: Menu, connection: AsyncConnection
) -> None:
    guest = as_guest(party.alex)
    await put_item(client, party.booking, menu.soup.id, {"quantity": 2}, guest)
    before = await stored_items(connection)

    missing = await remove_item(client, party.booking, menu.steak.id, guest)
    unknown = await remove_item(client, party.booking, uuid.uuid4(), guest)

    assert_error(missing, 404, "CART_ITEM_NOT_FOUND")
    assert_error(unknown, 404, "CART_ITEM_NOT_FOUND")
    assert await stored_items(connection) == before


@pytest.mark.parametrize(
    ("dish", "body", "status_code", "code"),
    [
        ("unknown", {"quantity": 1}, 404, "DISH_NOT_FOUND"),
        ("gone", {"quantity": 1}, 409, "DISH_UNAVAILABLE"),
        ("soup", {"quantity": 0}, 422, "VALIDATION_ERROR"),
        ("soup", {"quantity": -1}, 422, "VALIDATION_ERROR"),
        ("soup", {}, 422, "VALIDATION_ERROR"),
        ("soup", {"quantity": 21}, 400, "QUANTITY_TOO_LARGE"),
        ("soup", {"quantity": 1, "note": "N" * 201}, 422, "VALIDATION_ERROR"),
        ("not-a-uuid", {"quantity": 1}, 422, "VALIDATION_ERROR"),
    ],
)
async def test_a_bad_line_changes_nothing(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    connection: AsyncConnection,
    dish: str,
    body: dict[str, Any],
    status_code: int,
    code: str,
) -> None:
    guest = as_guest(party.alex)
    await put_item(client, party.booking, menu.steak.id, {"quantity": 1}, guest)
    before = await stored_items(connection)
    dish_ids = {"unknown": uuid.uuid4(), "gone": menu.gone.id, "soup": menu.soup.id}

    response = await put_item(client, party.booking, dish_ids.get(dish, dish), body, guest)

    assert_error(response, status_code, code)
    assert await stored_items(connection) == before


@pytest.mark.parametrize(("quantity", "note"), [(20, "N" * 200)])
async def test_a_line_takes_the_largest_quantity_and_the_longest_note(
    client: httpx2.AsyncClient, party: Party, menu: Menu, quantity: int, note: str
) -> None:
    response = await put_item(
        client,
        party.booking,
        menu.soup.id,
        {"quantity": quantity, "note": note},
        as_guest(party.alex),
    )

    assert response.status_code == 200, response.text
    assert lines_of(response.json()) == [("Test Soup", 20, note, 17000)]


async def test_a_dish_that_became_unavailable_can_only_be_lowered_noted_or_removed(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 3), (menu.soup, 1)], guest)
    await make_unavailable(session_factory, menu.steak)

    cart = await get_cart(client, party.booking, guest)
    raised = await put_item(client, party.booking, menu.steak.id, {"quantity": 4}, guest)
    noted = await put_item(
        client, party.booking, menu.steak.id, {"quantity": 3, "note": "Rare"}, guest
    )
    lowered = await put_item(client, party.booking, menu.steak.id, {"quantity": 2}, guest)
    removed = await remove_item(client, party.booking, menu.steak.id, guest)

    assert cart.status_code == 200, cart.text
    assert cart.json()["items"][0]["dish"] == dish_body(menu.steak, is_available=False)
    assert cart.json()["total_cents"] == 3 * 2400 + 850
    assert_error(raised, 409, "DISH_UNAVAILABLE")
    assert noted.status_code == 200, noted.text
    assert lines_of(noted.json())[0] == ("Test Steak", 3, "Rare", 7200)
    assert lowered.status_code == 200, lowered.text
    assert lines_of(lowered.json())[0] == ("Test Steak", 2, None, 4800)
    assert removed.status_code == 200, removed.text
    assert lines_of(removed.json()) == [("Test Soup", 1, None, 850)]


async def test_a_new_participant_has_an_empty_cart_and_no_submitted_parts(
    client: httpx2.AsyncClient, party: Party, menu: Menu
) -> None:
    cart = await get_cart(client, party.booking, as_guest(party.alex))
    mine = await my_preorder(client, party.booking, as_guest(party.alex))

    assert cart.status_code == 200, cart.text
    assert cart.json() == {"items": [], "total_cents": 0}
    assert mine.status_code == 200, mine.text
    assert mine.json() == {"parts": [], "total_cents": 0}


async def test_submit_moves_the_draft_into_one_submitted_part(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    connection: AsyncConnection,
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 2), (menu.soup, 1)], guest)
    await put_item(client, party.booking, menu.soup.id, {"quantity": 1, "note": NO_ONIONS}, guest)
    fake_clock.advance(minutes=1)

    response = await submit(client, party.booking, guest)

    assert response.status_code == 200, response.text
    part = response.json()
    assert set(part) == {"id", "submitted_at", "items", "total_cents"}
    uuid.UUID(part["id"])
    assert part["submitted_at"].endswith("+04:00")
    assert datetime.fromisoformat(part["submitted_at"]) == fake_clock.current
    assert [item["dish"] for item in part["items"]] == [
        dish_body(menu.steak),
        dish_body(menu.soup),
    ]
    assert lines_of(part) == [("Test Steak", 2, None, 4800), ("Test Soup", 1, NO_ONIONS, 850)]
    assert part["total_cents"] == 5650
    assert (await get_cart(client, party.booking, guest)).json() == {
        "items": [],
        "total_cents": 0,
    }
    assert (await my_preorder(client, party.booking, guest)).json() == {
        "parts": [part],
        "total_cents": 5650,
    }
    stored = await stored_items(connection)
    assert {row[4] for row in stored} == {"SUBMITTED"}
    assert {str(row[5]) for row in stored} == {part["id"]}


async def test_a_second_submit_adds_a_second_part_oldest_first(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 2), (menu.soup, 1)], guest)
    first = (await submit(client, party.booking, guest)).json()
    await fill(client, fake_clock, party.booking, [(menu.cake, 1), (menu.soup, 2)], guest)

    second = await submit(client, party.booking, guest)

    assert second.status_code == 200, second.text
    assert second.json()["id"] != first["id"]
    assert lines_of(second.json()) == [("Test Cake", 1, None, 650), ("Test Soup", 2, None, 1700)]
    assert second.json()["submitted_at"].endswith("+04:00")
    async with session_factory() as session:
        await session.execute(
            update(PreorderItem)
            .where(PreorderItem.submission_id == uuid.UUID(first["id"]))
            .values(updated_at=PreorderItem.updated_at)
        )
        await session.commit()
    mine = (await my_preorder(client, party.booking, guest)).json()
    assert mine == {"parts": [first, second.json()], "total_cents": 5650 + 2350}


@pytest.mark.parametrize("draft", ["empty", "unavailable"])
async def test_submit_is_refused_and_moves_nothing(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    draft: str,
) -> None:
    guest = as_guest(party.alex)
    if draft == "unavailable":
        await fill(client, fake_clock, party.booking, [(menu.steak, 2), (menu.soup, 1)], guest)
        await make_unavailable(session_factory, menu.soup)
    before = await stored_items(connection)

    response = await submit(client, party.booking, guest)

    if draft == "empty":
        assert_error(response, 409, "CART_EMPTY")
    else:
        assert_error(response, 409, "DISH_UNAVAILABLE")
    assert await stored_items(connection) == before
    assert (await my_preorder(client, party.booking, guest)).json() == {
        "parts": [],
        "total_cents": 0,
    }


async def test_submit_twice_without_a_new_draft_is_an_empty_cart(
    client: httpx2.AsyncClient, party: Party, menu: Menu, fake_clock: FakeClock
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.soup, 1)], guest)
    assert (await submit(client, party.booking, guest)).status_code == 200

    assert_error(await submit(client, party.booking, guest), 409, "CART_EMPTY")


async def test_the_menu_price_applies_at_read_time(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.soup, 2)], guest)
    await submit(client, party.booking, guest)
    await fill(client, fake_clock, party.booking, [(menu.soup, 1)], guest)
    async with session_factory() as session:
        await session.execute(update(Dish).where(Dish.id == menu.soup.id).values(price_cents=900))
        await session.commit()

    cart = (await get_cart(client, party.booking, guest)).json()
    mine = (await my_preorder(client, party.booking, guest)).json()

    assert cart["total_cents"] == 900
    assert cart["items"][0]["dish"]["price_cents"] == 900
    assert lines_of(mine["parts"][0]) == [("Test Soup", 2, None, 1800)]
    assert mine["total_cents"] == 1800


async def test_the_owner_fills_and_submits_like_a_guest(
    client: httpx2.AsyncClient, party: Party, menu: Menu, fake_clock: FakeClock
) -> None:
    await sign_in(client, ADA)

    await fill(client, fake_clock, party.booking, [(menu.cake, 2)])
    part = await submit(client, party.booking)

    assert part.status_code == 200, part.text
    assert lines_of(part.json()) == [("Test Cake", 2, None, 1300)]
    assert (await my_preorder(client, party.booking)).json() == {
        "parts": [part.json()],
        "total_cents": 1300,
    }
    client.cookies.clear()
    assert (await my_preorder(client, party.booking, as_guest(party.alex))).json() == {
        "parts": [],
        "total_cents": 0,
    }


async def test_a_joined_user_fills_their_own_cart(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=NOON, party_size=2
    )
    await add_participant(session_factory, booking_id=booking.id, user=users[GRACE])
    await sign_in(client, GRACE)

    response = await put_item(client, booking, menu.soup.id, {"quantity": 2})

    assert response.status_code == 200, response.text
    await sign_in(client, ADA)
    assert (await get_cart(client, booking)).json() == {"items": [], "total_cents": 0}


async def test_each_guest_sees_only_their_own_items(
    client: httpx2.AsyncClient, party: Party, menu: Menu, fake_clock: FakeClock
) -> None:
    alex, maria = as_guest(party.alex), as_guest(party.maria)
    await fill(client, fake_clock, party.booking, [(menu.steak, 1)], alex)
    await fill(client, fake_clock, party.booking, [(menu.cake, 2)], maria)
    alex_cart = (await get_cart(client, party.booking, alex)).json()
    maria_cart = (await get_cart(client, party.booking, maria)).json()
    await submit(client, party.booking, alex)
    await fill(client, fake_clock, party.booking, [(menu.soup, 1)], maria)
    await submit(client, party.booking, maria)

    alex_parts = (await my_preorder(client, party.booking, alex)).json()
    maria_parts = (await my_preorder(client, party.booking, maria)).json()

    assert lines_of(alex_cart) == [("Test Steak", 1, None, 2400)]
    assert lines_of(maria_cart) == [("Test Cake", 2, None, 1300)]
    assert [lines_of(part) for part in alex_parts["parts"]] == [[("Test Steak", 1, None, 2400)]]
    assert alex_parts["total_cents"] == 2400
    assert [lines_of(part) for part in maria_parts["parts"]] == [
        [("Test Cake", 2, None, 1300), ("Test Soup", 1, None, 850)]
    ]
    assert maria_parts["total_cents"] == 2150


async def test_a_cancelled_booking_closes_the_writes_and_keeps_the_reads(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    fake_clock: FakeClock,
    connection: AsyncConnection,
) -> None:
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 1)], guest)
    await submit(client, party.booking, guest)
    await fill(client, fake_clock, party.booking, [(menu.soup, 2)], guest)
    await sign_in(client, ADA)
    assert (await cancel(client, party.booking.id)).status_code == 200
    client.cookies.clear()
    before = await stored_items(connection)

    added = await put_item(client, party.booking, menu.cake.id, {"quantity": 1}, guest)
    changed = await put_item(client, party.booking, menu.soup.id, {"quantity": 1}, guest)
    removed = await remove_item(client, party.booking, menu.soup.id, guest)
    submitted = await submit(client, party.booking, guest)
    cart = await get_cart(client, party.booking, guest)
    mine = await my_preorder(client, party.booking, guest)

    for response in (added, changed, removed, submitted):
        assert_error(response, 409, "PREORDER_CLOSED")
    assert await stored_items(connection) == before
    assert cart.status_code == 200, cart.text
    assert lines_of(cart.json()) == [("Test Soup", 2, None, 1700)]
    assert mine.status_code == 200, mine.text
    assert mine.json()["total_cents"] == 2400


@pytest.mark.parametrize(("minutes", "is_open"), [(20, True), (21, False)])
async def test_the_preorder_closes_at_the_lock_before_the_start(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    minutes: int,
    is_open: bool,
) -> None:
    party = await add_party(session_factory, venue, users, starts_at=at(TODAY, 14))
    guest = as_guest(party.alex)
    await fill(client, fake_clock, party.booking, [(menu.steak, 1)], guest)
    fake_clock.current = START + timedelta(minutes=minutes)

    added = await put_item(client, party.booking, menu.soup.id, {"quantity": 1}, guest)
    removed = await remove_item(client, party.booking, menu.steak.id, guest)
    submitted = await submit(client, party.booking, guest)
    cart = await get_cart(client, party.booking, guest)

    if is_open:
        for response in (added, removed, submitted):
            assert response.status_code == 200, response.text
        assert lines_of(submitted.json()) == [("Test Soup", 1, None, 850)]
    else:
        for response in (added, removed, submitted):
            assert_error(response, 409, "PREORDER_CLOSED")
        assert lines_of(cart.json()) == [("Test Steak", 1, None, 2400)]
        assert len(await stored_items(connection)) == 1
    assert cart.status_code == 200, cart.text


@pytest.mark.parametrize(("quantity", "status_code"), [(5, 200), (6, 400)])
async def test_the_largest_quantity_follows_the_setting(
    client: httpx2.AsyncClient,
    app: FastAPI,
    party: Party,
    menu: Menu,
    quantity: int,
    status_code: int,
) -> None:
    settings = Settings(preorder=PreorderSettings(max_item_quantity=5))
    app.dependency_overrides[get_settings] = lambda: settings

    response = await put_item(
        client, party.booking, menu.soup.id, {"quantity": quantity}, as_guest(party.alex)
    )

    assert response.status_code == status_code, response.text
    if status_code == 400:
        assert response.json()["code"] == "QUANTITY_TOO_LARGE"


ROUTES = ["get-cart", "put-item", "remove-item", "submit", "my-pre-order"]


async def call(
    client: httpx2.AsyncClient,
    route: str,
    booking: Booking,
    dish_id: uuid.UUID,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    if route == "get-cart":
        return await get_cart(client, booking, headers)
    if route == "put-item":
        return await put_item(client, booking, dish_id, {"quantity": 1}, headers)
    if route == "remove-item":
        return await remove_item(client, booking, dish_id, headers)
    if route == "submit":
        return await submit(client, booking, headers)
    return await my_preorder(client, booking, headers)


@pytest.mark.parametrize("route", ROUTES)
async def test_every_route_needs_a_participant_of_the_booking(
    client: httpx2.AsyncClient,
    party: Party,
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
    route: str,
) -> None:
    expired = await add_guest(session_factory, name="Old", token="expired-token", expires_at=START)
    await add_participant(session_factory, booking_id=party.booking.id, guest=expired)

    nobody = await call(client, route, party.booking, menu.soup.id)
    expired_guest = await call(
        client, route, party.booking, menu.soup.id, as_guest("expired-token")
    )
    bad_access = await call(
        client,
        route,
        party.booking,
        menu.soup.id,
        {"Cookie": f"access_token=not-a-token; guest_token={party.alex}"},
    )
    other_guest = await call(client, route, party.booking, menu.soup.id, as_guest(party.bea))
    await sign_in(client, GRACE)
    stranger = await call(client, route, party.booking, menu.soup.id)
    unknown = await call(client, route, Booking(id=uuid.uuid4()), menu.soup.id)

    assert_error(nobody, 401, "NOT_AUTHENTICATED")
    assert_error(expired_guest, 401, "NOT_AUTHENTICATED")
    assert_error(bad_access, 401, "NOT_AUTHENTICATED")
    assert_error(other_guest, 404, "BOOKING_NOT_FOUND")
    assert_error(stranger, 404, "BOOKING_NOT_FOUND")
    assert_error(unknown, 404, "BOOKING_NOT_FOUND")


async def test_a_signed_in_user_wins_over_the_guest_cookie_of_a_participant(
    client: httpx2.AsyncClient, party: Party, menu: Menu
) -> None:
    await sign_in(client, GRACE)
    access_token = client.cookies["access_token"]
    client.cookies.clear()

    response = await get_cart(
        client,
        party.booking,
        {"Cookie": f"access_token={access_token}; guest_token={party.alex}"},
    )

    assert_error(response, 404, "BOOKING_NOT_FOUND")


async def test_set_reports_the_first_failing_check(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    party: Party,
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    closed = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=at(TOMORROW, 18),
        status=BookingStatus.CANCELLED,
    )
    guest = as_guest(party.alex)
    unknown = uuid.uuid4()

    assert_error(
        await put_item(client, party.booking, unknown, {"quantity": 0}), 422, "VALIDATION_ERROR"
    )
    assert_error(
        await put_item(client, party.booking, unknown, {"quantity": 21}), 401, "NOT_AUTHENTICATED"
    )
    assert_error(
        await put_item(client, closed, unknown, {"quantity": 21}, guest), 404, "BOOKING_NOT_FOUND"
    )
    await sign_in(client, ADA)
    assert_error(await put_item(client, closed, unknown, {"quantity": 21}), 409, "PREORDER_CLOSED")
    client.cookies.clear()
    assert_error(
        await put_item(client, party.booking, unknown, {"quantity": 21}, guest),
        400,
        "QUANTITY_TOO_LARGE",
    )
    assert_error(
        await put_item(client, party.booking, unknown, {"quantity": 1}, guest),
        404,
        "DISH_NOT_FOUND",
    )
    assert_error(
        await put_item(client, party.booking, menu.gone.id, {"quantity": 1}, guest),
        409,
        "DISH_UNAVAILABLE",
    )


async def test_remove_and_submit_report_the_first_failing_check(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    party: Party,
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    closed = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=at(TOMORROW, 18),
        status=BookingStatus.CANCELLED,
    )
    guest = as_guest(party.alex)

    assert_error(await remove_item(client, closed, menu.soup.id), 401, "NOT_AUTHENTICATED")
    assert_error(await submit(client, closed), 401, "NOT_AUTHENTICATED")
    assert_error(await remove_item(client, closed, menu.soup.id, guest), 404, "BOOKING_NOT_FOUND")
    assert_error(await submit(client, closed, guest), 404, "BOOKING_NOT_FOUND")
    await sign_in(client, ADA)
    assert_error(await remove_item(client, closed, menu.soup.id), 409, "PREORDER_CLOSED")
    assert_error(await submit(client, closed), 409, "PREORDER_CLOSED")
    client.cookies.clear()
    assert_error(
        await remove_item(client, party.booking, menu.soup.id, guest), 404, "CART_ITEM_NOT_FOUND"
    )
    assert_error(await submit(client, party.booking, guest), 409, "CART_EMPTY")
