import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    START,
    TODAY,
    TOMORROW,
    TZ,
    FakeClock,
    Venue,
    add_booking,
    add_participant,
    at,
    sign_in,
)
from support.fake_chat_model import Call, FakeChatModel, Text
from support.sse import parse_events

from app.common.ai_tools import AiToolContext
from app.config.settings import (
    AssistantSettings,
    BookingSettings,
    OpenAISettings,
    Settings,
    get_settings,
)
from app.features.assistant.endpoints.dependencies import get_chat_model
from app.features.assistant.services.toolkit_builder import ToolkitBuilder
from app.features.core.bookings.enums import BookingStatus
from app.features.core.menu.enums import DishCategory
from app.main import create_app
from app.model_registry import Booking, DiningTable, Dish, Location, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

SESSIONS = "/api/v1/assistant/sessions"
QUESTION = "What can you tell me?"


@dataclass
class Menu:
    soup: Dish
    steak: Dish
    cake: Dish


@pytest.fixture
def booking_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
def fake() -> FakeChatModel:
    return FakeChatModel(scripts=[])


@pytest.fixture
def app(fake: FakeChatModel, booking_overrides: dict[str, Any]) -> FastAPI:
    app = create_app()
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr("test")),
        assistant=AssistantSettings(),
        booking=BookingSettings(**booking_overrides),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_chat_model] = lambda: fake
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


def make_dish(slug: str, category: DishCategory, price_cents: int) -> Dish:
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
        is_available=True,
        popularity=1,
        prep_minutes=10,
        image_key=f"dishes/{slug}.webp",
        created_at=START,
    )


@pytest.fixture
async def menu(session_factory: async_sessionmaker[AsyncSession]) -> Menu:
    menu = Menu(
        soup=make_dish("tools-soup", DishCategory.APPETIZER, 850),
        steak=make_dish("tools-steak", DishCategory.MAIN_COURSE, 2400),
        cake=make_dish("tools-cake", DishCategory.DESSERT, 650),
    )
    async with session_factory() as session:
        session.add_all([menu.soup, menu.steak, menu.cake])
        await session.commit()
    return menu


async def ask(
    client: httpx2.AsyncClient, fake: FakeChatModel, *calls: Call
) -> list[tuple[str, Any]]:
    fake.scripts = [list(calls), [Text("Here you are.")]] if calls else [[Text("Hello.")]]
    await sign_in(client, ADA)
    created = await client.post(SESSIONS)
    assert created.status_code == 201, created.text
    response = await client.post(
        f"{SESSIONS}/{created.json()['id']}/messages", json={"text": QUESTION}
    )
    assert response.status_code == 200, response.text
    events = parse_events(response.text)
    assert [name for name, _ in events] == ["thinking"] * len(fake.scripts) + ["chunk", "done"]
    return events


def tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


def only_result(fake: FakeChatModel) -> tuple[ToolMessage, Any]:
    (message,) = tool_messages(fake.received[1])
    return message, json.loads(str(message.content))


async def test_list_locations_answers_both_locations_with_table_counts_oldest_first(
    client: httpx2.AsyncClient, users: dict[str, User], venue: Venue, fake: FakeChatModel
) -> None:
    await ask(client, fake, Call("list_locations", {}, "call_1"))

    message, result = only_result(fake)
    assert message.status == "success"
    assert result == [
        {
            "id": str(venue.first.id),
            "address": "Old Town Square",
            "description": "About old-town-square",
            "table_count": 3,
        },
        {
            "id": str(venue.second.id),
            "address": "River Embankment",
            "description": "About river-embankment",
            "table_count": 2,
        },
    ]


async def test_find_tables_lists_the_free_start_ranges_of_fitting_tables(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 13)
    )

    await ask(
        client,
        fake,
        Call("find_tables", {"date": TOMORROW.isoformat(), "party_size": 4}, "call_four"),
        Call("find_tables", {"date": TOMORROW.isoformat(), "party_size": 6}, "call_six"),
    )

    four, six = tool_messages(fake.received[1])
    assert four.status == "success"
    assert json.loads(str(four.content)) == {
        "total": 2,
        "locations": [
            {
                "id": str(venue.first.id),
                "address": "Old Town Square",
                "tables": [
                    {
                        "id": str(venue.four.id),
                        "label": "Table 2",
                        "capacity": 4,
                        "by_request": False,
                        "free_start_ranges": ["10:00-11:30", "14:30-21:30"],
                    }
                ],
            },
            {
                "id": str(venue.second.id),
                "address": "River Embankment",
                "tables": [
                    {
                        "id": str(venue.other.id),
                        "label": "Table 1",
                        "capacity": 4,
                        "by_request": False,
                        "free_start_ranges": ["10:00-21:30"],
                    }
                ],
            },
        ],
    }
    assert [
        (table["capacity"], table["by_request"])
        for location in json.loads(str(six.content))["locations"]
        for table in location["tables"]
    ] == [(6, True), (8, True)]


async def test_find_tables_at_one_location_lists_only_its_tables(
    client: httpx2.AsyncClient, users: dict[str, User], venue: Venue, fake: FakeChatModel
) -> None:
    arguments = {
        "date": TOMORROW.isoformat(),
        "party_size": 4,
        "location_id": str(venue.second.id),
    }

    await ask(client, fake, Call("find_tables", arguments, "call_1"))

    _, result = only_result(fake)
    assert result["total"] == 1
    (location,) = result["locations"]
    assert location["id"] == str(venue.second.id)
    assert [table["id"] for table in location["tables"]] == [str(venue.other.id)]


async def test_find_tables_at_an_unknown_location_answers_location_not_found(
    client: httpx2.AsyncClient, users: dict[str, User], venue: Venue, fake: FakeChatModel
) -> None:
    arguments = {"date": TOMORROW.isoformat(), "party_size": 4, "location_id": str(uuid.uuid4())}

    await ask(client, fake, Call("find_tables", arguments, "call_1"))

    message, result = only_result(fake)
    assert message.status == "error"
    assert result["error"] == "LOCATION_NOT_FOUND"


@pytest.mark.parametrize(
    ("booked_midday", "expected_length", "ranges"),
    [
        (False, 4879, ["10:00-21:30"]),
        (True, 5359, ["10:00-11:30", "14:30-21:30"]),
    ],
)
async def test_find_tables_over_a_full_restaurant_fits_the_tool_result_limit(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
    booked_midday: bool,
    expected_length: int,
    ranges: list[str],
) -> None:
    addresses = ["48 Rustaveli Avenue", "14 Baratashvili Street", "9 Abashidze Street"]
    async with session_factory() as session:
        locations = [
            Location(
                slug=f"seeded-{number}",
                address=address,
                description=f"About {address}",
                image_key=f"locations/seeded-{number}.jpg",
                created_at=START + timedelta(minutes=number),
            )
            for number, address in enumerate(addresses)
        ]
        session.add_all(locations)
        await session.flush()
        tables = [
            DiningTable(
                location_id=locations[number % 3].id,
                label=f"Table {number + 1}",
                capacity=2 + number % 3,
            )
            for number in range(32)
        ]
        session.add_all(tables)
        await session.commit()
    if booked_midday:
        for table in tables:
            await add_booking(
                session_factory, user=users[GRACE], table=table, starts_at=at(TOMORROW, 13)
            )

    await ask(
        client,
        fake,
        Call("find_tables", {"date": TOMORROW.isoformat(), "party_size": 2}, "call_1"),
    )

    (message,) = tool_messages(fake.received[1])
    content = str(message.content)
    assert len(content) == expected_length
    assert len(content) < AssistantSettings().tool_result_max_chars
    result = json.loads(content)
    assert list(result) == ["total", "locations"]
    assert result["total"] == 32
    listed = [table for location in result["locations"] for table in location["tables"]]
    assert len(listed) == 32
    assert all(table["free_start_ranges"] == ranges for table in listed)


async def test_find_tables_at_a_start_booked_everywhere_answers_no_tables(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
) -> None:
    for table in (venue.small, venue.four, venue.other):
        await add_booking(
            session_factory, user=users[GRACE], table=table, starts_at=at(TOMORROW, 19)
        )

    await ask(
        client,
        fake,
        Call(
            "find_tables",
            {"date": TOMORROW.isoformat(), "party_size": 2, "time": "19:00"},
            "call_1",
        ),
    )

    _, result = only_result(fake)
    assert result == {"total": 0, "locations": []}


async def test_find_tables_with_bad_arguments_answers_an_error_naming_the_field(
    client: httpx2.AsyncClient, users: dict[str, User], venue: Venue, fake: FakeChatModel
) -> None:
    await ask(
        client,
        fake,
        Call("find_tables", {"date": TOMORROW.isoformat(), "party_size": "four"}, "call_1"),
    )

    message, result = only_result(fake)
    assert (message.tool_call_id, message.status) == ("call_1", "error")
    assert result["error"] == "INVALID_ARGUMENTS"
    assert "party_size" in result["message"]


async def test_find_tables_past_the_horizon_answers_the_domain_error(
    client: httpx2.AsyncClient, users: dict[str, User], venue: Venue, fake: FakeChatModel
) -> None:
    beyond = TODAY + timedelta(days=31)

    await ask(
        client,
        fake,
        Call("find_tables", {"date": beyond.isoformat(), "party_size": 2}, "call_1"),
    )

    message, result = only_result(fake)
    assert message.status == "error"
    assert result["error"] == "DATE_OUT_OF_RANGE"
    assert result["message"]


async def test_list_my_bookings_answers_upcoming_soonest_first_then_the_latest_ten_past(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
) -> None:
    ada, grace = users[ADA], users[GRACE]
    past = [
        await add_booking(
            session_factory,
            user=ada,
            table=venue.small,
            starts_at=at(TODAY - timedelta(days=d), 12),
        )
        for d in range(1, 13)
    ]
    joined = await add_booking(
        session_factory, user=grace, table=venue.other, starts_at=at(TOMORROW, 19), party_size=3
    )
    await add_participant(session_factory, booking_id=joined.id, user=ada)
    cancelled = await add_booking(
        session_factory,
        user=ada,
        table=venue.four,
        starts_at=at(TOMORROW, 13),
        status=BookingStatus.CANCELLED,
    )
    in_progress = await add_booking(
        session_factory, user=ada, table=venue.small, starts_at=at(TODAY, 12)
    )

    await ask(client, fake, Call("list_my_bookings", {}, "call_1"))

    message, result = only_result(fake)
    assert message.status == "success"
    assert [booking["id"] for booking in result] == [
        str(booking.id) for booking in [in_progress, cancelled, joined, *past[:10]]
    ]
    assert result[1] == {
        "id": str(cancelled.id),
        "status": "CANCELLED",
        "starts_at": "2026-11-13T13:00:00+04:00",
        "ends_at": "2026-11-13T14:30:00+04:00",
        "party_size": 2,
        "table": {"label": "Table 2", "capacity": 4},
        "location": {"address": "Old Town Square"},
        "role": "OWNER",
        "participants": [{"name": "Ada", "role": "OWNER"}],
    }
    assert result[2] == {
        "id": str(joined.id),
        "status": "CONFIRMED",
        "starts_at": "2026-11-13T19:00:00+04:00",
        "ends_at": "2026-11-13T20:30:00+04:00",
        "party_size": 3,
        "table": {"label": "Table 1", "capacity": 4},
        "location": {"address": "River Embankment"},
        "role": "GUEST",
        "participants": [{"name": "Grace", "role": "OWNER"}, {"name": "Ada", "role": "GUEST"}],
    }
    assert result[3]["starts_at"] == "2026-11-11T12:00:00+04:00"


async def own_booking(
    session_factory: async_sessionmaker[AsyncSession], users: dict[str, User], venue: Venue
) -> Booking:
    return await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 13)
    )


async def test_get_my_preorder_answers_the_cart_and_the_submitted_parts_with_prices(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    menu: Menu,
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
    fake_clock: FakeClock,
) -> None:
    booking = await own_booking(session_factory, users, venue)
    await sign_in(client, ADA)
    cart = f"{BOOKINGS}/{booking.id}/cart"
    put_cake = await client.put(f"{cart}/items/{menu.cake.id}", json={"quantity": 1})
    assert put_cake.status_code == 200, put_cake.text
    assert (await client.post(f"{cart}/submit")).status_code == 200
    fake_clock.advance(minutes=5)
    for dish, body in [
        (menu.soup, {"quantity": 2, "note": "No onion"}),
        (menu.steak, {"quantity": 1}),
    ]:
        assert (await client.put(f"{cart}/items/{dish.id}", json=body)).status_code == 200
    route_cart = (await client.get(cart)).json()

    await ask(client, fake, Call("get_my_preorder", {"booking_id": str(booking.id)}, "call_1"))

    message, result = only_result(fake)
    assert message.status == "success"
    soup_line = {
        "dish_id": str(menu.soup.id),
        "name": "Tools Soup",
        "quantity": 2,
        "note": "No onion",
        "price": "8.50",
        "line_total": "17.00",
        "is_available": True,
    }
    steak_line = {
        "dish_id": str(menu.steak.id),
        "name": "Tools Steak",
        "quantity": 1,
        "note": None,
        "price": "24.00",
        "line_total": "24.00",
        "is_available": True,
    }
    by_dish = {str(menu.soup.id): soup_line, str(menu.steak.id): steak_line}
    assert result == {
        "cart": {
            "items": [by_dish[line["dish"]["id"]] for line in route_cart["items"]],
            "total": "41.00",
        },
        "submitted_parts": [
            {
                "submitted_at": "2026-11-12T13:10:00+04:00",
                "items": [
                    {
                        "dish_id": str(menu.cake.id),
                        "name": "Tools Cake",
                        "quantity": 1,
                        "note": None,
                        "price": "6.50",
                        "line_total": "6.50",
                        "is_available": True,
                    }
                ],
                "total": "6.50",
            }
        ],
        "submitted_total": "6.50",
    }


async def test_get_my_preorder_for_a_booking_the_user_has_not_joined_is_not_found(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
) -> None:
    foreign = await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 13)
    )

    await ask(client, fake, Call("get_my_preorder", {"booking_id": str(foreign.id)}, "call_1"))

    message, result = only_result(fake)
    assert message.status == "error"
    assert result == {"error": "BOOKING_NOT_FOUND", "message": "No booking with this id exists."}


@pytest.mark.parametrize(
    "booking_overrides",
    [
        {
            "duration_minutes": 60,
            "max_online_party_size": 3,
            "horizon_days": 21,
            "cancel_cutoff_minutes": 45,
            "preorder_lock_minutes": 50,
        }
    ],
)
async def test_the_prompt_carries_the_booking_rules_from_the_settings(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel
) -> None:
    await ask(client, fake)

    (received,) = fake.received
    system = received[0]
    assert isinstance(system, SystemMessage)
    prompt = str(system.text)
    assert prompt.startswith("Always answer in the language of the guest's latest message")
    for rule in (
        "all times in Asia/Tbilisi",
        "a visit starts from 10:00 to 21:30 every 30 minutes",
        "a booking lasts 60 minutes and can be extended to at most 180 minutes",
        "the restaurant closes at 23:00",
        "a party of up to 3 people is booked at once",
        "a party of up to 8 people sends a request that the staff confirm",
        "a request must start more than 120 minutes from now",
        "bookings open from today up to 21 days ahead",
        "a booking can be changed or cancelled until 45 minutes before its start, "
        "and a change keeps the booking on the same day",
        "the pre-order can be changed until 50 minutes before the start",
        "call find_tables and read the free starts across the tables",
        "editing or cancelling a booking and changing the cart are not available yet",
    ):
        assert rule in prompt, rule
    local = START.astimezone(TZ)
    assert prompt.endswith(f"Today is {local:%A, %d %B %Y}, and the time is 13:10 (Asia/Tbilisi).")
    assert {tool.name for tool in fake.bound_tools} == {
        "list_menu",
        "get_dish",
        "list_locations",
        "find_tables",
        "list_my_bookings",
        "create_booking",
        "get_my_preorder",
    }


async def test_no_tool_argument_names_a_user() -> None:
    context = AiToolContext(
        user_id=uuid.uuid4(),
        sessionmaker=async_sessionmaker(),
        public_base_url="https://media.example.com",
        booking=BookingSettings(),
        max_item_quantity=20,
    )
    for tool in ToolkitBuilder(context).build():
        fields = tool.args
        assert not {name for name in fields if "user" in name}, tool.name
        for name, field in fields.items():
            assert field.get("description"), f"{tool.name}.{name}"
