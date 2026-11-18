import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    START,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    assert_error,
    at,
    sign_in,
)
from support.fake_chat_model import Act, Call, FakeChatModel, Raise, Text, Usage, Wait
from support.sse import parse_events

from app.config.settings import (
    AssistantSettings,
    BookingSettings,
    OpenAISettings,
    Settings,
    get_settings,
)
from app.features.assistant.endpoints.dependencies import get_chat_model
from app.features.assistant.enums import AssistantActionStatus
from app.features.core.bookings.repositories import BookingRepository
from app.main import create_app
from app.model_registry import AssistantAction, AssistantModelCall, Booking, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

SESSIONS = "/api/v1/assistant/sessions"
QUESTION = "Book the table for four tomorrow at 19:00, please."
ANSWER = "Here is the booking for you to confirm."
COMMENT = "It is booked, see you tomorrow."
TTL = timedelta(hours=24)
DONE_FIXED = "Done: it is in your reservations."
CARD_KEYS = {"id", "kind", "status", "card", "created_at", "expires_at", "result", "error"}


@pytest.fixture
def assistant_overrides() -> dict[str, Any]:
    return {}


@dataclass
class Models:
    """The turn and the apply each get their own fake, so the tools one binds never show in
    the other."""

    turn: FakeChatModel
    comment: FakeChatModel
    current: FakeChatModel
    clock: FakeClock


@pytest.fixture
def models(fake_clock: FakeClock) -> Models:
    turn = FakeChatModel(scripts=[])
    return Models(turn=turn, comment=FakeChatModel(scripts=[]), current=turn, clock=fake_clock)


@pytest.fixture
def app(models: Models, assistant_overrides: dict[str, Any]) -> FastAPI:
    app = create_app()
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr("test")),
        assistant=AssistantSettings(**assistant_overrides),
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


def booking_call(
    table_id: uuid.UUID, *, hour: int = 19, party_size: int = 4, call_id: str = "call_book"
) -> Call:
    return Call(
        "create_booking",
        {
            "table_id": str(table_id),
            "date": TOMORROW.isoformat(),
            "time": f"{hour:02d}:00",
            "party_size": party_size,
        },
        call_id,
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
    # Each message gets its own moment, so the read-back order never falls to the random ids.
    first, *rest = scripts
    tick = Act(lambda: models.clock.advance(seconds=1))
    models.turn.scripts = [*models.turn.scripts, [tick, *first], *rest]
    models.clock.advance(seconds=1)
    response = await client.post(f"{SESSIONS}/{session_id}/messages", json={"text": QUESTION})
    assert response.status_code == 200, response.text
    return parse_events(response.text)


async def propose(
    client: httpx2.AsyncClient, models: Models, session_id: str, *calls: Call
) -> dict[str, Any]:
    events = await turn(client, models, session_id, list(calls), [Text(ANSWER)])
    names = [name for name, _ in events]
    assert names == ["thinking", "thinking", "chunk", "action", "done"], events
    action: dict[str, Any] = events[3][1]
    return action


def action_path(session_id: str, action_id: str, suffix: str = "") -> str:
    return f"{SESSIONS}/{session_id}/actions/{action_id}{suffix}"


async def apply(
    client: httpx2.AsyncClient, models: Models, session_id: str, action_id: str
) -> httpx2.Response:
    models.current = models.comment
    models.clock.advance(seconds=1)
    return await client.post(action_path(session_id, action_id, "/apply"))


async def applied_events(
    client: httpx2.AsyncClient, models: Models, session_id: str, action_id: str
) -> list[tuple[str, Any]]:
    response = await apply(client, models, session_id, action_id)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_events(response.text)


async def read_session(client: httpx2.AsyncClient, session_id: str) -> dict[str, Any]:
    response = await client.get(f"{SESSIONS}/{session_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def stored_actions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[AssistantAction]:
    async with session_factory() as session:
        rows = await session.scalars(select(AssistantAction).order_by(AssistantAction.created_at))
        return list(rows)


async def bookings_of(session_factory: async_sessionmaker[AsyncSession], user: User) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Booking).where(Booking.user_id == user.id)
        )
        return int(count or 0)


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def tool_results(messages: list[Any]) -> list[dict[str, Any]]:
    return [json.loads(str(m.content)) for m in messages if isinstance(m, ToolMessage)]


FOUR_CARD = {
    "title": "Book a table",
    "fields": [
        {"label": "Location", "value": "Old Town Square"},
        {"label": "Table", "value": "Table 2, up to 4 guests"},
        {"label": "Date", "value": "Fri, 13 Nov 2026"},
        {"label": "Time", "value": "19:00 – 20:30"},
        {"label": "Guests", "value": "4"},
    ],
    "notice": None,
    "confirm_label": "Book",
}


async def test_a_proposal_streams_a_pending_card_and_books_nothing(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(client, models, session_id, booking_call(venue.four.id))

    assert set(action) == CARD_KEYS
    assert action["kind"] == "booking.create"
    assert action["status"] == "PENDING"
    assert action["card"] == FOUR_CARD
    assert (action["result"], action["error"]) == (None, None)
    assert moment(action["created_at"]) == START + timedelta(seconds=2)
    assert moment(action["expires_at"]) == START + timedelta(seconds=2) + TTL
    (result,) = tool_results(models.turn.received[1])
    assert result == {"status": "awaiting_confirmation", "card": FOUR_CARD}
    assert await bookings_of(session_factory, users[ADA]) == 0
    (stored,) = await stored_actions(session_factory)
    assert stored.payload == {
        "table_id": str(venue.four.id),
        "starts_at": at(TOMORROW, 19).isoformat(),
        "party_size": 4,
    }
    assert stored.payload["starts_at"] == "2026-11-13T19:00:00+04:00"
    assert stored.user_id == users[ADA].id
    body = await read_session(client, session_id)
    question, answer = body["messages"]
    assert question["action"] is None
    assert answer["text"] == ANSWER
    assert answer["action"] == action
    assert stored.message_id == uuid.UUID(answer["id"])


async def test_a_refused_proposal_lets_the_model_try_another_table_in_the_same_turn(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    action = await propose(
        client,
        models,
        session_id,
        booking_call(venue.four.id, call_id="call_taken"),
        booking_call(venue.other.id, call_id="call_free"),
    )

    refused, proposed = tool_results(models.turn.received[1])
    assert refused["error"] == "SLOT_UNAVAILABLE"
    assert refused["message"]
    assert proposed["status"] == "awaiting_confirmation"
    assert action["card"]["fields"][0] == {"label": "Location", "value": "River Embankment"}
    (stored,) = await stored_actions(session_factory)
    assert stored.payload["table_id"] == str(venue.other.id)


async def test_a_second_proposal_in_one_turn_is_refused(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    await propose(
        client,
        models,
        session_id,
        booking_call(venue.four.id, call_id="call_first"),
        booking_call(venue.other.id, call_id="call_second"),
    )

    first, second = tool_results(models.turn.received[1])
    assert first["status"] == "awaiting_confirmation"
    assert second == {"error": "ONE_PROPOSAL_PER_TURN"}
    (stored,) = await stored_actions(session_factory)
    assert stored.payload["table_id"] == str(venue.four.id)


async def test_a_newer_card_cancels_the_pending_one_or_marks_an_expired_one_expired(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    first = await propose(client, models, session_id, booking_call(venue.four.id))
    fake_clock.advance(minutes=1)

    second = await propose(client, models, session_id, booking_call(venue.other.id))

    first_now = await client.get(action_path(session_id, first["id"]))
    assert first_now.json()["status"] == "CANCELLED"
    assert second["status"] == "PENDING"
    fake_clock.advance(hours=25)
    await sign_in(client, ADA)

    third = await propose(client, models, session_id, booking_call(venue.four.id, hour=20))

    statuses = {str(action.id): action.status for action in await stored_actions(session_factory)}
    assert statuses == {
        first["id"]: AssistantActionStatus.CANCELLED,
        second["id"]: AssistantActionStatus.EXPIRED,
        third["id"]: AssistantActionStatus.PENDING,
    }


@pytest.mark.parametrize("assistant_overrides", [{"max_rounds": 2}])
async def test_a_turn_ending_on_the_fallback_still_stores_and_sends_its_proposal(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    events = await turn(
        client,
        models,
        session_id,
        [booking_call(venue.four.id)],
        [Call("list_my_bookings", {}, "call_more")],
    )

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "action", "done"]
    assert events[3][1]["status"] == "PENDING"
    (stored,) = await stored_actions(session_factory)
    assert str(stored.id) == events[3][1]["id"]


async def test_a_turn_ending_with_an_error_drops_its_proposal(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    events = await turn(
        client,
        models,
        session_id,
        [booking_call(venue.four.id)],
        [Raise(RuntimeError("provider down"))],
    )

    assert [name for name, _ in events] == ["thinking", "thinking", "error"]
    assert await stored_actions(session_factory) == []


async def test_a_request_party_gets_a_notice_and_its_applied_booking_waits_for_the_staff(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.six.id, party_size=6))
    assert action["card"]["notice"] == "Sent as a request; the restaurant confirms it."
    assert action["card"]["fields"][1] == {"label": "Table", "value": "Table 3, up to 6 guests"}
    models.comment.scripts = [[Text(COMMENT)]]

    events = await applied_events(client, models, session_id, action["id"])

    applied = events[0][1]
    assert applied["status"] == "APPLIED"
    assert applied["result"]["status"] == "PENDING"
    listed = (await client.get(BOOKINGS)).json()
    booking_id = applied["result"]["booking_id"]
    assert [(b["id"], b["status"]) for b in listed] == [(booking_id, "PENDING")]


async def test_apply_books_the_table_and_streams_a_comment_from_a_model_with_no_tools(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    fake_clock.advance(minutes=2)
    models.comment.scripts = [[Text("It is "), Text("booked."), Usage(500, None, 20)]]

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "chunk", "chunk", "done"]
    applied = events[0][1]
    assert set(applied) == CARD_KEYS
    assert applied["id"] == action["id"]
    assert applied["status"] == "APPLIED"
    assert applied["error"] is None
    assert applied["card"] == FOUR_CARD
    assert set(applied["result"]) == {"booking_id", "status"}
    assert applied["result"]["status"] == "CONFIRMED"
    listed = (await client.get(BOOKINGS)).json()
    assert [b["id"] for b in listed] == [applied["result"]["booking_id"]]
    assert moment(listed[0]["starts_at"]) == at(TOMORROW, 19)
    assert listed[0]["party_size"] == 4
    done = events[-1][1]
    body = await read_session(client, session_id)
    comment = body["messages"][-1]
    assert (comment["id"], comment["role"], comment["text"]) == (
        done["message_id"],
        "ASSISTANT",
        "It is booked.",
    )
    assert comment["action"] is None
    assert body["messages"][1]["action"]["status"] == "APPLIED"
    assert models.comment.bound_tools == []
    (received,) = models.comment.received
    assert isinstance(received[0], SystemMessage)
    note = received[-1]
    assert isinstance(note, HumanMessage)
    assert str(note.text) == (
        "The guest pressed Book on the card 'Book a table'. Outcome: APPLIED, "
        f"{json.dumps(applied['result'])}. Comment on it briefly in the guest's language."
    )
    assert isinstance(received[-2], AIMessage)
    assert str(received[-2].text).endswith("[Proposed booking.create: APPLIED]")
    assert len(body["messages"]) == 3
    async with session_factory() as session:
        calls = await session.scalar(select(func.count()).select_from(AssistantModelCall))
    assert calls == 1


async def test_apply_after_the_slot_was_taken_fails_and_books_nothing(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
    )
    models.comment.scripts = [[Text("Sorry, that table was just taken.")]]

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "chunk", "done"]
    failed = events[0][1]
    assert failed["status"] == "FAILED"
    assert failed["result"] is None
    assert failed["error"]["code"] == "SLOT_UNAVAILABLE"
    assert failed["error"]["message"]
    assert await bookings_of(session_factory, users[ADA]) == 0
    note = models.comment.received[0][-1]
    assert "Outcome: FAILED" in str(note.text)
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.FAILED


async def test_a_failing_comment_keeps_the_booking_and_ends_with_an_error(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Raise(RuntimeError("provider down"))]]

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "error"]
    assert events[0][1]["status"] == "APPLIED"
    assert events[-1][1]["code"] == "ASSISTANT_PROVIDER_ERROR"
    assert await bookings_of(session_factory, users[ADA]) == 1
    assert len((await read_session(client, session_id))["messages"]) == 2


async def test_a_second_apply_books_nothing_and_replays_the_applied_action(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Text(COMMENT)]]
    first = await applied_events(client, models, session_id, action["id"])

    second = await applied_events(client, models, session_id, action["id"])

    assert second == [
        ("action", first[0][1]),
        ("done", {"message_id": None, "created_at": None}),
    ]
    assert await bookings_of(session_factory, users[ADA]) == 1
    assert len(models.comment.received) == 1


async def test_apply_after_a_cancel_is_not_pending(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    cancelled = await client.post(action_path(session_id, action["id"], "/cancel"))
    assert cancelled.status_code == 200, cancelled.text

    response = await apply(client, models, session_id, action["id"])

    assert_error(response, 409, "ASSISTANT_ACTION_NOT_PENDING")
    assert await bookings_of(session_factory, users[ADA]) == 0
    assert models.comment.received == []


@pytest.mark.parametrize("state", ["FAILED", "EXPIRED"])
async def test_apply_of_a_failed_or_expired_action_is_not_pending(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
    state: str,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    if state == "FAILED":
        await add_booking(
            session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
        )
        models.comment.scripts = [[Text(COMMENT)]]
        await applied_events(client, models, session_id, action["id"])
    else:
        fake_clock.advance(hours=24)
        await sign_in(client, ADA)

    response = await apply(client, models, session_id, action["id"])

    assert_error(response, 409, "ASSISTANT_ACTION_NOT_PENDING")
    assert await bookings_of(session_factory, users[ADA]) == 0


async def test_cancel_of_an_applied_action_is_not_pending(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Text(COMMENT)]]
    await applied_events(client, models, session_id, action["id"])

    response = await client.post(action_path(session_id, action["id"], "/cancel"))

    assert_error(response, 409, "ASSISTANT_ACTION_NOT_PENDING")


async def test_an_expired_action_reads_as_expired_and_apply_writes_nothing(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    fake_clock.advance(hours=24, seconds=1)
    await sign_in(client, ADA)

    got = await client.get(action_path(session_id, action["id"]))
    body = await read_session(client, session_id)
    applied = await apply(client, models, session_id, action["id"])
    cancelled = await client.post(action_path(session_id, action["id"], "/cancel"))

    assert got.status_code == 200, got.text
    assert got.json() == {**action, "status": "EXPIRED"}
    assert body["messages"][1]["action"]["status"] == "EXPIRED"
    assert_error(applied, 409, "ASSISTANT_ACTION_NOT_PENDING")
    assert_error(cancelled, 409, "ASSISTANT_ACTION_NOT_PENDING")
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.PENDING
    assert stored.resolved_at is None


async def test_cancel_twice_answers_cancelled_both_times(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    fake_clock.advance(minutes=1)

    first = await client.post(action_path(session_id, action["id"], "/cancel"))
    second = await client.post(action_path(session_id, action["id"], "/cancel"))

    assert first.status_code == 200, first.text
    assert first.json() == {**action, "status": "CANCELLED"}
    assert second.json() == first.json()
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.CANCELLED
    assert stored.resolved_at == START + timedelta(minutes=1, seconds=2)


async def test_another_users_or_an_unknown_action_is_not_found(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, GRACE)
    grace_session = await create_session(client)
    foreign = await propose(client, models, grace_session, booking_call(venue.four.id))
    await sign_in(client, ADA)
    ada_session = await create_session(client)

    for session_id, action_id in [
        (grace_session, foreign["id"]),
        (ada_session, foreign["id"]),
        (ada_session, str(uuid.uuid4())),
    ]:
        responses = [
            await client.get(action_path(session_id, action_id)),
            await client.post(action_path(session_id, action_id, "/cancel")),
            await apply(client, models, session_id, action_id),
        ]
        for response in responses:
            assert_error(response, 404, "ASSISTANT_ACTION_NOT_FOUND")
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.PENDING


@pytest.mark.parametrize(
    ("taken", "status", "comment"),
    [
        (False, "APPLIED", DONE_FIXED),
        (True, "FAILED", "That did not work: "),
    ],
)
async def test_apply_with_the_budget_spent_runs_and_comments_with_a_fixed_text(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    taken: bool,
    status: str,
    comment: str,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    if taken:
        await add_booking(
            session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
        )
    async with session_factory() as session:
        session.add(
            AssistantModelCall(
                model="gpt-4.1-mini",
                input_tokens=1000,
                cached_input_tokens=0,
                output_tokens=100,
                cost_micro_usd=1_000_000,
                created_at=START,
            )
        )
        await session.commit()

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "chunk", "done"]
    outcome = events[0][1]
    assert outcome["status"] == status
    expected = comment if not taken else comment + outcome["error"]["message"]
    assert events[2][1] == {"text": expected}
    assert models.comment.received == []
    assert (await read_session(client, session_id))["messages"][-1]["text"] == expected


async def test_the_next_turn_sees_the_status_of_the_proposed_action(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Text(COMMENT)]]
    await applied_events(client, models, session_id, action["id"])

    await turn(client, models, session_id, [Text("Anything else?")])

    history = models.turn.received[-1]
    proposed = history[2]
    assert isinstance(proposed, AIMessage)
    assert str(proposed.text) == f"{ANSWER}\n[Proposed booking.create: APPLIED]"
    assert str(history[3].text) == COMMENT


async def test_the_history_line_of_a_failed_action_carries_its_error_code(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
    )
    models.comment.scripts = [[Text(COMMENT)]]
    await applied_events(client, models, session_id, action["id"])

    await turn(client, models, session_id, [Text("Anything else?")])

    proposed = models.turn.received[-1][2]
    assert str(proposed.text) == f"{ANSWER}\n[Proposed booking.create: FAILED SLOT_UNAVAILABLE]"


async def test_the_prompt_says_the_card_is_the_confirmation(
    client: httpx2.AsyncClient, users: dict[str, User], models: Models
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    await turn(client, models, session_id, [Text("Hello.")])

    prompt = str(models.turn.received[0][0].text)
    for rule in (
        "propose it with create_booking as soon as the guest has given the date, the time and "
        "the party size",
        "When several tables fit, pick one yourself, at the location the guest named, else the "
        "first in the find_tables result, and call create_booking at once",
        "never ask the guest to choose a table number or a location unless the guest asked to "
        "choose",
        "A location_id is only ever an id returned by list_locations or a location id in a "
        "find_tables result; to filter by a location the guest named, look its id up first",
        "the card is the confirmation",
        "nothing is booked until the guest applies the card",
    ):
        assert rule in prompt, rule
    assert "create_booking" in {tool.name for tool in models.turn.bound_tools}


async def test_apply_that_hits_the_exclusion_constraint_rolls_back_to_the_savepoint_and_fails(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 19)
    )

    async def no_overlap(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(BookingRepository, "table_has_confirmed_overlap", no_overlap)
    models.comment.scripts = [[Text(COMMENT)]]

    events = await applied_events(client, models, session_id, action["id"])

    failed = events[0][1]
    assert failed["status"] == "FAILED"
    assert failed["error"]["code"] == "SLOT_UNAVAILABLE"
    assert [name for name, _ in events] == ["action", "thinking", "chunk", "done"]
    assert await bookings_of(session_factory, users[ADA]) == 0
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.FAILED


async def test_apply_of_an_unregistered_kind_fails_instead_of_staying_pending(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    async with session_factory() as session:
        await session.execute(
            update(AssistantAction)
            .where(AssistantAction.id == uuid.UUID(action["id"]))
            .values(kind="booking.unknown")
        )
        await session.commit()
    models.comment.scripts = [[Text(COMMENT)]]

    events = await applied_events(client, models, session_id, action["id"])

    failed = events[0][1]
    assert failed["status"] == "FAILED"
    assert failed["error"]["code"] == "UNKNOWN_ACTION"
    assert failed["error"]["message"]
    assert await bookings_of(session_factory, users[ADA]) == 0
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.FAILED


@pytest.mark.parametrize("assistant_overrides", [{"turn_timeout_seconds": 1}])
async def test_a_hanging_comment_times_out_and_the_booking_stays(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Wait(30)]]

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "error"]
    assert events[0][1]["status"] == "APPLIED"
    assert events[-1][1]["code"] == "ASSISTANT_TIMEOUT"
    assert await bookings_of(session_factory, users[ADA]) == 1
    assert len((await read_session(client, session_id))["messages"]) == 2


async def test_a_comment_with_no_text_is_answered_with_the_fixed_text(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    models.comment.scripts = [[Usage(500, None, 0)]]

    events = await applied_events(client, models, session_id, action["id"])

    assert [name for name, _ in events] == ["action", "thinking", "chunk", "done"]
    assert events[2][1] == {"text": DONE_FIXED}
    comment = (await read_session(client, session_id))["messages"][-1]
    assert (comment["id"], comment["text"]) == (events[-1][1]["message_id"], DONE_FIXED)


async def test_an_action_under_another_session_of_the_same_user_is_not_found(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    venue: Venue,
    models: Models,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    action = await propose(client, models, session_id, booking_call(venue.four.id))
    other_session = await create_session(client)

    responses = [
        await client.get(action_path(other_session, action["id"])),
        await client.post(action_path(other_session, action["id"], "/cancel")),
        await apply(client, models, other_session, action["id"]),
    ]

    for response in responses:
        assert_error(response, 404, "ASSISTANT_ACTION_NOT_FOUND")
    (stored,) = await stored_actions(session_factory)
    assert stored.status is AssistantActionStatus.PENDING
