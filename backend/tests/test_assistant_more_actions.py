import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    TODAY,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    add_participant,
    at,
    edit,
    sign_in,
)
from support.fake_chat_model import Act, Call, FakeChatModel, Text
from support.preorder import Menu, fill, get_cart, my_preorder, put_item
from support.sse import parse_events

from app.config.settings import (
    AssistantSettings,
    BookingSettings,
    OpenAISettings,
    Settings,
    get_settings,
)
from app.features.assistant.endpoints.dependencies import get_chat_model
from app.features.core.bookings.enums import BookingStatus
from app.main import create_app
from app.model_registry import AssistantAction, Booking, Dish, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

SESSIONS = "/api/v1/assistant/sessions"
QUESTION = "Please change it."
ANSWER = "Here is the change for you to confirm."
COMMENT = "Done."
EVENING = at(TOMORROW, 19)
BOOKING_LABEL = "Fri, 13 Nov 2026, 19:00, Old Town Square"
NOTE = "No onions"


@dataclass
class Models:
    turn: FakeChatModel
    comment: FakeChatModel
    current: FakeChatModel
    clock: FakeClock


@pytest.fixture
def models(fake_clock: FakeClock) -> Models:
    turn = FakeChatModel(scripts=[])
    return Models(turn=turn, comment=FakeChatModel(scripts=[]), current=turn, clock=fake_clock)


@pytest.fixture
def app(models: Models) -> FastAPI:
    app = create_app()
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr("test")),
        assistant=AssistantSettings(),
        booking=BookingSettings(),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_chat_model] = lambda: models.current
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
async def evening(
    session_factory: async_sessionmaker[AsyncSession], users: dict[str, User], venue: Venue
) -> Booking:
    return await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=EVENING, party_size=4
    )


async def create_session(client: httpx2.AsyncClient) -> str:
    response = await client.post(SESSIONS)
    assert response.status_code == 201, response.text
    session_id: str = response.json()["id"]
    return session_id


async def turn(
    client: httpx2.AsyncClient, models: Models, session_id: str, *scripts: list[Any]
) -> list[tuple[str, Any]]:
    models.current = models.turn
    first, *rest = scripts
    tick = Act(lambda: models.clock.advance(seconds=1))
    models.turn.scripts = [*models.turn.scripts, [tick, *first], *rest]
    models.clock.advance(seconds=1)
    response = await client.post(f"{SESSIONS}/{session_id}/messages", json={"text": QUESTION})
    assert response.status_code == 200, response.text
    return parse_events(response.text)


async def call_tools(
    client: httpx2.AsyncClient, models: Models, session_id: str, *calls: Call
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """One turn with these tool calls; the tool results and the action the turn streamed."""
    first_call = len(models.turn.received)
    events = await turn(client, models, session_id, list(calls), [Text(ANSWER)])
    actions = [data for name, data in events if name == "action"]
    results = [
        json.loads(str(message.content))
        for message in models.turn.received[first_call + 1]
        if isinstance(message, ToolMessage)
    ]
    return results, actions[0] if actions else None


async def propose(
    client: httpx2.AsyncClient, models: Models, session_id: str, call: Call
) -> dict[str, Any]:
    (result,), action = await call_tools(client, models, session_id, call)
    assert result.get("status") == "awaiting_confirmation", result
    assert action is not None
    assert action["status"] == "PENDING"
    assert result["card"] == action["card"]
    return action


async def apply(
    client: httpx2.AsyncClient, models: Models, session_id: str, action_id: str
) -> dict[str, Any]:
    models.current = models.comment
    models.comment.scripts = [*models.comment.scripts, [Text(COMMENT)]]
    models.clock.advance(seconds=1)
    response = await client.post(f"{SESSIONS}/{session_id}/actions/{action_id}/apply")
    assert response.status_code == 200, response.text
    events = parse_events(response.text)
    assert events[0][0] == "action", events
    action: dict[str, Any] = events[0][1]
    return action


async def stored_actions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[AssistantAction]:
    async with session_factory() as session:
        return list(await session.scalars(select(AssistantAction)))


async def reload(session_factory: async_sessionmaker[AsyncSession], booking: Booking) -> Booking:
    async with session_factory() as session:
        stored = await session.get(Booking, booking.id)
        assert stored is not None
        return stored


def edit_call(booking: Booking, **values: Any) -> Call:
    return Call("edit_booking", {"booking_id": str(booking.id), **values}, f"call_{uuid.uuid4()}")


def cancel_call(booking: Booking) -> Call:
    return Call("cancel_booking", {"booking_id": str(booking.id)}, f"call_{uuid.uuid4()}")


def set_call(booking: Booking, dish_id: uuid.UUID, quantity: int, **values: Any) -> Call:
    return Call(
        "set_cart_item",
        {"booking_id": str(booking.id), "dish_id": str(dish_id), "quantity": quantity, **values},
        f"call_{uuid.uuid4()}",
    )


def remove_call(booking: Booking, dish_id: uuid.UUID) -> Call:
    return Call(
        "remove_cart_item",
        {"booking_id": str(booking.id), "dish_id": str(dish_id)},
        f"call_{uuid.uuid4()}",
    )


def submit_call(booking: Booking) -> Call:
    return Call("submit_preorder", {"booking_id": str(booking.id)}, f"call_{uuid.uuid4()}")


def field(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


async def cart_lines(client: httpx2.AsyncClient, booking: Booking) -> list[tuple[str, int, Any]]:
    response = await get_cart(client, booking)
    assert response.status_code == 200, response.text
    return [
        (item["dish"]["name"], item["quantity"], item["note"]) for item in response.json()["items"]
    ]


async def test_an_edit_is_proposed_with_the_before_values_and_changes_only_on_apply(
    client: httpx2.AsyncClient,
    models: Models,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(client, models, session_id, edit_call(evening, time="20:00"))

    assert action["kind"] == "booking.edit"
    assert action["card"] == {
        "title": "Change the booking",
        "fields": [
            field("Location", "Old Town Square"),
            field("Table", "Table 2, up to 4 guests"),
            field("Date", "Fri, 13 Nov 2026"),
            field("Time", "20:00 – 21:30"),
            field("Guests", "4"),
            field("Before", "19:00 – 20:30, 4 guests"),
        ],
        "notice": None,
        "confirm_label": "Change",
    }
    assert (await reload(session_factory, evening)).starts_at == EVENING

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "APPLIED"
    assert applied["result"] == {"booking_id": str(evening.id), "status": "CONFIRMED"}
    stored = await reload(session_factory, evening)
    assert (stored.starts_at, stored.ends_at) == (at(TOMORROW, 20), at(TOMORROW, 21, 30))
    assert stored.party_size == 4


async def test_an_edit_that_changes_nothing_makes_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client,
        models,
        session_id,
        edit_call(evening),
        edit_call(evening, time="19:00", party_size=4, duration_minutes=90),
    )

    assert results == [{"error": "NOTHING_TO_CHANGE"}, {"error": "NOTHING_TO_CHANGE"}]
    assert action is None
    assert await stored_actions(session_factory) == []


async def test_an_edit_the_service_refuses_makes_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    users: dict[str, User],
    venue: Venue,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 21)
    )
    joined = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=at(TOMORROW, 12)
    )
    await add_participant(session_factory, booking_id=joined.id, user=users[ADA])
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client,
        models,
        session_id,
        edit_call(evening, time="20:00"),
        edit_call(joined, time="13:00"),
    )

    assert [result["error"] for result in results] == ["SLOT_UNAVAILABLE", "BOOKING_NOT_FOUND"]
    assert action is None


@pytest.mark.parametrize(
    ("starts_at", "party_size", "duration_minutes"),
    [(EVENING, 3, 90), (at(TOMORROW, 19, 30), 4, 90), (EVENING, 4, 120)],
    ids=["party", "start", "duration"],
)
async def test_an_edit_made_on_the_website_after_the_card_fails_the_apply(
    client: httpx2.AsyncClient,
    models: Models,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
    starts_at: datetime,
    party_size: int,
    duration_minutes: int,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, edit_call(evening, time="20:00"))
    website = await edit(client, evening.id, starts_at, party_size, duration_minutes)
    assert website.status_code == 200, website.text

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "FAILED"
    assert applied["error"] == {
        "code": "BOOKING_CHANGED",
        "message": "The booking changed after this card was made.",
    }
    stored = await reload(session_factory, evening)
    assert (stored.starts_at, stored.party_size, stored.ends_at) == (
        starts_at,
        party_size,
        starts_at + timedelta(minutes=duration_minutes),
    )


async def test_an_edit_of_the_party_and_the_length_pins_the_new_and_the_before_values(
    client: httpx2.AsyncClient,
    models: Models,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(
        client, models, session_id, edit_call(evening, party_size=3, duration_minutes=120)
    )

    assert action["card"]["fields"][3:] == [
        field("Time", "19:00 – 21:00"),
        field("Guests", "3"),
        field("Before", "19:00 – 20:30, 4 guests"),
    ]
    (stored_action,) = await stored_actions(session_factory)
    assert stored_action.payload == {
        "booking_id": str(evening.id),
        "starts_at": "2026-11-13T19:00:00+04:00",
        "party_size": 3,
        "duration_minutes": 120,
        "before": {
            "starts_at": "2026-11-13T19:00:00+04:00",
            "party_size": 4,
            "duration_minutes": 90,
        },
    }
    await apply(client, models, session_id, action["id"])

    stored = await reload(session_factory, evening)
    assert (stored.party_size, stored.ends_at) == (3, at(TOMORROW, 21))


async def test_an_edit_time_with_an_offset_is_refused_as_invalid(
    client: httpx2.AsyncClient, models: Models, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (result,), action = await call_tools(
        client, models, session_id, edit_call(evening, time="20:00+02:00")
    )

    assert result["error"] == "INVALID_ARGUMENTS"
    assert result["message"].startswith("time")
    assert action is None


async def test_a_confirmed_booking_and_a_pending_request_are_cancelled_on_apply(
    client: httpx2.AsyncClient,
    models: Models,
    users: dict[str, User],
    venue: Venue,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.eight,
        starts_at=at(TOMORROW + timedelta(days=1), 19),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(client, models, session_id, cancel_call(evening))

    assert action["kind"] == "booking.cancel"
    assert action["card"] == {
        "title": "Cancel the booking",
        "fields": [
            field("Location", "Old Town Square"),
            field("Table", "Table 2, up to 4 guests"),
            field("Date", "Fri, 13 Nov 2026"),
            field("Time", "19:00 – 20:30"),
            field("Guests", "4"),
        ],
        "notice": "This cannot be undone.",
        "confirm_label": "Yes, cancel it",
    }
    assert (await reload(session_factory, evening)).status == BookingStatus.CONFIRMED
    applied = await apply(client, models, session_id, action["id"])
    assert applied["result"] == {"booking_id": str(evening.id), "status": "CANCELLED"}

    second = await propose(client, models, session_id, cancel_call(request))
    assert second["card"]["fields"][0] == field("Location", "River Embankment")
    applied = await apply(client, models, session_id, second["id"])

    assert applied["result"] == {"booking_id": str(request.id), "status": "CANCELLED"}
    assert (await reload(session_factory, evening)).status == BookingStatus.CANCELLED
    assert (await reload(session_factory, request)).status == BookingStatus.CANCELLED


async def test_a_cancel_inside_the_cutoff_makes_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    soon = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TODAY, 13, 30)
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (result,), action = await call_tools(client, models, session_id, cancel_call(soon))

    assert result["error"] == "CANCELLATION_CLOSED"
    assert action is None


async def test_a_cancel_of_a_joined_or_cancelled_booking_makes_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    joined = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=EVENING
    )
    await add_participant(session_factory, booking_id=joined.id, user=users[ADA])
    cancelled = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.four,
        starts_at=EVENING,
        status=BookingStatus.CANCELLED,
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client, models, session_id, cancel_call(joined), cancel_call(cancelled)
    )

    assert [result["error"] for result in results] == [
        "BOOKING_NOT_FOUND",
        "BOOKING_ALREADY_CANCELLED",
    ]
    assert action is None


async def test_set_item_sets_the_total_quantity_and_keeps_the_note_when_omitted(
    client: httpx2.AsyncClient, models: Models, menu: Menu, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    first = await propose(
        client, models, session_id, set_call(evening, menu.soup.id, 2, note=f"  {NOTE}  ")
    )

    assert first["kind"] == "cart.set_item"
    assert first["card"] == {
        "title": "Update your pre-order cart",
        "fields": [
            field("Booking", BOOKING_LABEL),
            field("Dish", "Test Soup"),
            field("Quantity", "2"),
            field("Note", NOTE),
            field("Line total", "$17.00"),
        ],
        "notice": None,
        "confirm_label": "Save",
    }
    assert await cart_lines(client, evening) == []
    applied = await apply(client, models, session_id, first["id"])
    assert applied["result"] == {"booking_id": str(evening.id), "cart_total": "17.00"}
    assert await cart_lines(client, evening) == [("Test Soup", 2, NOTE)]

    second = await propose(client, models, session_id, set_call(evening, menu.soup.id, 3))

    assert second["card"]["fields"][2:] == [
        field("Quantity", "3"),
        field("Note", NOTE),
        field("Line total", "$25.50"),
        field("Before", f"2, note: {NOTE}"),
    ]
    applied = await apply(client, models, session_id, second["id"])
    assert applied["result"] == {"booking_id": str(evening.id), "cart_total": "25.50"}
    assert await cart_lines(client, evening) == [("Test Soup", 3, NOTE)]


async def test_an_empty_note_removes_the_lines_note(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
) -> None:
    await sign_in(client, ADA)
    await put_item(client, evening, menu.soup.id, {"quantity": 2, "note": NOTE})
    session_id = await create_session(client)

    action = await propose(client, models, session_id, set_call(evening, menu.soup.id, 2, note=""))

    assert action["card"]["fields"][2:] == [
        field("Quantity", "2"),
        field("Line total", "$17.00"),
        field("Before", f"2, note: {NOTE}"),
    ]
    await apply(client, models, session_id, action["id"])
    assert await cart_lines(client, evening) == [("Test Soup", 2, None)]


@pytest.mark.parametrize(
    "website", [{"quantity": 5, "note": NOTE}, {"quantity": 3, "note": "Extra spicy"}]
)
async def test_a_line_changed_on_the_website_after_the_card_fails_the_set_item(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    website: dict[str, Any],
) -> None:
    await sign_in(client, ADA)
    await put_item(client, evening, menu.soup.id, {"quantity": 3, "note": NOTE})
    session_id = await create_session(client)
    action = await propose(client, models, session_id, set_call(evening, menu.soup.id, 5))
    assert action["card"]["fields"][-1] == field("Before", f"3, note: {NOTE}")
    changed = await put_item(client, evening, menu.soup.id, website)
    assert changed.status_code == 200, changed.text

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "FAILED"
    assert applied["error"] == {
        "code": "CART_CHANGED",
        "message": "The cart changed after this card was made.",
    }
    assert await cart_lines(client, evening) == [
        ("Test Soup", website["quantity"], website["note"])
    ]


async def test_a_line_without_a_note_shows_no_note_field(
    client: httpx2.AsyncClient, models: Models, menu: Menu, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(client, models, session_id, set_call(evening, menu.steak.id, 1))

    assert [item["label"] for item in action["card"]["fields"]] == [
        "Booking",
        "Dish",
        "Quantity",
        "Line total",
    ]


async def test_set_item_the_service_refuses_makes_no_card(
    client: httpx2.AsyncClient, models: Models, menu: Menu, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client,
        models,
        session_id,
        set_call(evening, menu.gone.id, 1),
        set_call(evening, menu.soup.id, 21),
    )

    assert [result["error"] for result in results] == ["DISH_UNAVAILABLE", "QUANTITY_TOO_LARGE"]
    assert action is None


async def test_bad_cart_arguments_name_the_field(
    client: httpx2.AsyncClient, models: Models, menu: Menu, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (zero, long_note), action = await call_tools(
        client,
        models,
        session_id,
        set_call(evening, menu.soup.id, 0),
        set_call(evening, menu.soup.id, 1, note="x" * 201),
    )

    assert zero["error"] == "INVALID_ARGUMENTS"
    assert zero["message"].startswith("quantity")
    assert long_note["error"] == "INVALID_ARGUMENTS"
    assert long_note["message"].startswith("note")
    assert action is None


async def test_remove_shows_the_quantity_and_removes_the_line_on_apply(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    await fill(client, fake_clock, evening, [(menu.soup, 2), (menu.steak, 1)])
    session_id = await create_session(client)

    action = await propose(client, models, session_id, remove_call(evening, menu.soup.id))

    assert action["kind"] == "cart.remove_item"
    assert action["card"] == {
        "title": "Remove from your pre-order cart",
        "fields": [
            field("Booking", BOOKING_LABEL),
            field("Dish", "Test Soup"),
            field("Quantity", "2"),
        ],
        "notice": None,
        "confirm_label": "Remove",
    }
    assert len(await cart_lines(client, evening)) == 2
    applied = await apply(client, models, session_id, action["id"])

    assert applied["result"] == {"booking_id": str(evening.id), "cart_total": "24.00"}
    assert await cart_lines(client, evening) == [("Test Steak", 1, None)]


async def test_removing_a_dish_not_in_the_cart_makes_no_card(
    client: httpx2.AsyncClient, models: Models, menu: Menu, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (result,), action = await call_tools(
        client, models, session_id, remove_call(evening, menu.soup.id)
    )

    assert result["error"] == "CART_ITEM_NOT_FOUND"
    assert action is None


async def test_cart_changes_and_submit_inside_the_preorder_lock_make_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    soon = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TODAY, 13, 30)
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client,
        models,
        session_id,
        set_call(soon, menu.soup.id, 1),
        submit_call(soon),
    )

    assert [result["error"] for result in results] == ["PREORDER_CLOSED", "PREORDER_CLOSED"]
    assert action is None


async def test_submit_shows_the_items_and_sends_the_part_on_apply(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    fake_clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    await fill(client, fake_clock, evening, [(menu.steak, 2), (menu.soup, 1)])
    session_id = await create_session(client)

    action = await propose(client, models, session_id, submit_call(evening))

    assert action["kind"] == "preorder.submit"
    assert action["card"] == {
        "title": "Send your pre-order",
        "fields": [
            field("Booking", BOOKING_LABEL),
            field("Items", "2 × Test Steak, 1 × Test Soup"),
            field("Total", "$56.50"),
        ],
        "notice": "A sent part is final; a new cart can follow.",
        "confirm_label": "Send",
    }
    (stored,) = await stored_actions(session_factory)
    assert sorted(stored.payload["items"], key=lambda item: item["quantity"]) == [
        {"dish_id": str(menu.soup.id), "quantity": 1},
        {"dish_id": str(menu.steak.id), "quantity": 2},
    ]
    assert (await my_preorder(client, evening)).json()["parts"] == []

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "APPLIED"
    (part,) = (await my_preorder(client, evening)).json()["parts"]
    assert applied["result"] == {
        "booking_id": str(evening.id),
        "part_id": part["id"],
        "total": "56.50",
    }
    assert await cart_lines(client, evening) == []


async def test_a_line_added_after_the_submit_card_fails_the_apply_and_sends_nothing(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    await fill(client, fake_clock, evening, [(menu.steak, 2), (menu.soup, 1)])
    session_id = await create_session(client)
    action = await propose(client, models, session_id, submit_call(evening))
    added = await put_item(client, evening, menu.cake.id, {"quantity": 1})
    assert added.status_code == 200, added.text

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "FAILED"
    assert applied["error"] == {
        "code": "CART_CHANGED",
        "message": "The cart changed after this card was made.",
    }
    assert (await my_preorder(client, evening)).json()["parts"] == []
    assert len(await cart_lines(client, evening)) == 3

    await turn(client, models, session_id, [Text("Anything else?")])

    proposed = models.turn.received[-1][2]
    assert isinstance(proposed, AIMessage)
    assert str(proposed.text) == f"{ANSWER}\n[Proposed preorder.submit: FAILED CART_CHANGED]"


async def test_a_price_change_after_the_submit_card_fails_the_apply_and_sends_nothing(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    fake_clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    await fill(client, fake_clock, evening, [(menu.steak, 2), (menu.soup, 1)])
    session_id = await create_session(client)
    action = await propose(client, models, session_id, submit_call(evening))
    async with session_factory() as session:
        await session.execute(update(Dish).where(Dish.id == menu.steak.id).values(price_cents=2600))
        await session.commit()

    applied = await apply(client, models, session_id, action["id"])

    assert applied["status"] == "FAILED"
    assert applied["error"]["code"] == "CART_CHANGED"
    assert (await my_preorder(client, evening)).json()["parts"] == []
    assert len(await cart_lines(client, evening)) == 2


async def test_submitting_an_empty_cart_makes_no_card(
    client: httpx2.AsyncClient, models: Models, evening: Booking
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (result,), action = await call_tools(client, models, session_id, submit_call(evening))

    assert result["error"] == "CART_EMPTY"
    assert action is None


async def test_cart_actions_on_a_booking_the_user_has_not_joined_make_no_card(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    foreign = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=EVENING
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    results, action = await call_tools(
        client,
        models,
        session_id,
        set_call(foreign, menu.soup.id, 1),
        remove_call(foreign, menu.soup.id),
        submit_call(foreign),
    )

    assert [result["error"] for result in results] == ["BOOKING_NOT_FOUND"] * 3
    assert action is None


async def test_a_second_proposal_of_another_kind_in_one_turn_is_refused(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    (first, second), action = await call_tools(
        client, models, session_id, set_call(evening, menu.soup.id, 1), cancel_call(evening)
    )

    assert first["status"] == "awaiting_confirmation"
    assert second == {"error": "ONE_PROPOSAL_PER_TURN"}
    assert action is not None
    assert action["kind"] == "cart.set_item"
    assert len(await stored_actions(session_factory)) == 1


async def test_a_joined_guest_sets_only_their_own_cart_line(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    users: dict[str, User],
    venue: Venue,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    hosted = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=EVENING, party_size=3
    )
    await add_participant(session_factory, booking_id=hosted.id, user=users[ADA])
    await sign_in(client, GRACE)
    await put_item(client, hosted, menu.soup.id, {"quantity": 4})
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(client, models, session_id, set_call(hosted, menu.soup.id, 1))
    await apply(client, models, session_id, action["id"])

    assert await cart_lines(client, hosted) == [("Test Soup", 1, None)]
    await sign_in(client, GRACE)
    assert await cart_lines(client, hosted) == [("Test Soup", 4, None)]


async def test_the_prompt_proposes_every_change_as_a_card(
    client: httpx2.AsyncClient, users: dict[str, User], models: Models
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    await turn(client, models, session_id, [Text("Hello.")])

    prompt = str(models.turn.received[0][0].text)
    assert "not available yet" not in prompt
    for rule in (
        "as soon as the guest names what to change",
        "never invent an id",
        "only where the guest's role is OWNER",
        "a move to another day is explained, not proposed",
        "propose the new total",
        "only when the guest asks to send the pre-order",
        "call list_my_bookings first and never ask the guest for the booking's date, time or "
        "party size",
        "when exactly one upcoming booking matches, use it without asking",
        "find its id with list_menu instead of asking",
    ):
        assert rule in prompt, rule
    assert {
        "edit_booking",
        "cancel_booking",
        "set_cart_item",
        "remove_cart_item",
        "submit_preorder",
    } <= {tool.name for tool in models.turn.bound_tools}


async def test_a_dry_run_leaves_no_booking_or_cart_change(
    client: httpx2.AsyncClient,
    models: Models,
    menu: Menu,
    evening: Booking,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    await propose(client, models, session_id, cancel_call(evening))
    await propose(client, models, session_id, set_call(evening, menu.soup.id, 2))

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.status == BookingStatus.CANCELLED)
        )
    assert count == 0
    assert await cart_lines(client, evening) == []
    assert (await client.get(BOOKINGS)).json()[0]["status"] == "CONFIRMED"
