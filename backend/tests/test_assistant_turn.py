import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI, Request
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import ADA, GRACE, START, FakeClock, assert_error, sign_in
from support.fake_chat_model import Act, Call, FakeChatModel, Raise, Text, Wait
from support.sse import parse_events

from app.config.settings import AssistantSettings, OpenAISettings, Settings, get_settings
from app.features.assistant.endpoints.dependencies import build_chat_model, get_chat_model
from app.features.assistant.enums import AssistantMessageRole
from app.features.assistant.repositories import AssistantSessionRepository
from app.features.assistant.services.assistant_turn_service import AssistantTurnService
from app.features.assistant.services.exceptions import AssistantUnavailableError
from app.features.core.menu.dto import DishPage, DishView
from app.features.core.menu.enums import DishCategory
from app.features.core.menu.services.dish_catalog_service import DishCatalogService
from app.main import create_app
from app.model_registry import AssistantMessage, AssistantSession, Dish, User

pytestmark = pytest.mark.anyio

SESSIONS = "/api/v1/assistant/sessions"
QUESTION = "What desserts do you have today and what is in the cheesecake, please?"
TITLE_CHARS = 60
TRUNCATED = " …[truncated]"
MINUTE = timedelta(minutes=1)
USER = AssistantMessageRole.USER
ASSISTANT = AssistantMessageRole.ASSISTANT
CARD_KEYS = {
    "id",
    "name",
    "category",
    "price",
    "is_available",
    "weight_grams",
    "calories",
    "prep_minutes",
}
DETAIL_KEYS = CARD_KEYS | {"description", "protein", "fats", "carbs", "vitamins"}


@dataclass
class Menu:
    soup: Dish
    steak: Dish
    cake: Dish


@pytest.fixture
def assistant_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
def fake() -> FakeChatModel:
    return FakeChatModel(scripts=[])


@pytest.fixture
def app(fake: FakeChatModel, assistant_overrides: dict[str, Any]) -> FastAPI:
    app = create_app()
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr("test")),
        assistant=AssistantSettings(**assistant_overrides),
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


def make_dish(
    slug: str, category: DishCategory, price_cents: int, prep_minutes: int, popularity: int
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
        is_available=True,
        popularity=popularity,
        prep_minutes=prep_minutes,
        image_key=f"dishes/{slug}.webp",
        created_at=START,
    )


@pytest.fixture
async def menu(
    connection: AsyncConnection, session_factory: async_sessionmaker[AsyncSession]
) -> Menu:
    await connection.execute(text("DELETE FROM dishes"))
    menu = Menu(
        soup=make_dish("test-soup", DishCategory.APPETIZER, 850, 10, 1),
        steak=make_dish("test-steak", DishCategory.MAIN_COURSE, 2400, 25, 2),
        cake=make_dish("test-cake", DishCategory.DESSERT, 650, 15, 3),
    )
    async with session_factory() as session:
        session.add_all([menu.soup, menu.steak, menu.cake])
        await session.commit()
    return menu


async def create_session(client: httpx2.AsyncClient) -> str:
    response = await client.post(SESSIONS)
    assert response.status_code == 201, response.text
    session_id: str = response.json()["id"]
    return session_id


async def send(
    client: httpx2.AsyncClient, session_id: str, text: str = QUESTION
) -> httpx2.Response:
    return await client.post(f"{SESSIONS}/{session_id}/messages", json={"text": text})


async def stream(client: httpx2.AsyncClient, session_id: str) -> list[tuple[str, Any]]:
    response = await send(client, session_id)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_events(response.text)


async def read_session(client: httpx2.AsyncClient, session_id: str) -> dict[str, Any]:
    response = await client.get(f"{SESSIONS}/{session_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def add_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    role: AssistantMessageRole,
    text: str,
    created_at: datetime,
) -> None:
    message = AssistantMessage(
        session_id=uuid.UUID(session_id), role=role, text=text, created_at=created_at
    )
    async with session_factory() as session:
        session.add(message)
        await session.execute(
            update(AssistantSession)
            .where(AssistantSession.id == message.session_id)
            .values(updated_at=created_at)
        )
        await session.commit()


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


def payload(message: ToolMessage) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(str(message.content))
    return decoded


def logged_errors(caplog: pytest.LogCaptureFixture) -> list[BaseException]:
    errors: list[BaseException] = []
    for record in caplog.records:
        if record.levelno < logging.ERROR or record.exc_info is None:
            continue
        error = record.exc_info[1]
        while error is not None:
            errors.append(error)
            error = error.__cause__
    return errors


async def test_a_plain_answer_streams_chunks_then_done_and_saves_both_messages(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel, fake_clock: FakeClock
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Text("We have "), Act(lambda: fake_clock.advance(seconds=3)), Text("three desserts.")]
    ]
    assert len(QUESTION) == 70

    response = await send(client, session_id)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_events(response.text)
    assert events[:3] == [
        ("thinking", {}),
        ("chunk", {"text": "We have "}),
        ("chunk", {"text": "three desserts."}),
    ]
    ((name, done),) = events[3:]
    assert name == "done"
    assert set(done) == {"message_id", "created_at"}
    assert moment(done["created_at"]) == START + timedelta(seconds=3)
    body = await read_session(client, session_id)
    assert body["title"] == QUESTION[:TITLE_CHARS]
    assert len(body["title"]) == TITLE_CHARS
    assert moment(body["updated_at"]) == START + timedelta(seconds=3)
    assert [(m["role"], m["text"], moment(m["created_at"])) for m in body["messages"]] == [
        ("USER", QUESTION, START),
        ("ASSISTANT", "We have three desserts.", START + timedelta(seconds=3)),
    ]
    assert body["messages"][1]["id"] == done["message_id"]
    (received,) = fake.received
    system, question = received
    assert isinstance(system, SystemMessage)
    assert "Ada" in str(system.text)
    assert isinstance(question, HumanMessage)
    assert str(question.text) == QUESTION


async def test_a_tool_round_thinks_twice_and_feeds_the_dishes_back_to_the_model(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [
            Call("list_menu", {}, "call_all"),
            Call("list_menu", {"category": "DESSERT"}, "call_dessert"),
        ],
        [Text("Three desserts.")],
    ]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    first, second = fake.received
    assert second[:2] == first
    assert isinstance(second[2], AIMessage)
    assert [call["name"] for call in second[2].tool_calls] == ["list_menu", "list_menu"]
    everything, desserts = tool_messages(second)
    assert (everything.tool_call_id, everything.status) == ("call_all", "success")
    result = payload(everything)
    assert result["total"] == 3
    assert [dish["name"] for dish in result["dishes"]] == ["Test Cake", "Test Steak", "Test Soup"]
    assert result["dishes"][0] == {
        "id": str(menu.cake.id),
        "name": "Test Cake",
        "category": "DESSERT",
        "price": "6.50",
        "is_available": True,
        "weight_grams": 300,
        "calories": 450,
        "prep_minutes": 15,
    }
    assert desserts.tool_call_id == "call_dessert"
    assert payload(desserts) == {"total": 1, "dishes": [result["dishes"][0]]}


async def test_a_dish_detail_carries_its_description_and_nutrition(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("get_dish", {"dish_id": str(menu.cake.id)}, "call_1")], [Text("Cake.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    (detail,) = tool_messages(fake.received[1])
    dish = payload(detail)
    assert set(dish) == DETAIL_KEYS
    assert dish["id"] == str(menu.cake.id)
    assert dish["description"] == "About test-cake"
    assert dish["price"] == "6.50"
    assert (dish["calories"], dish["protein"], dish["fats"], dish["carbs"], dish["vitamins"]) == (
        450,
        "18g",
        "10g",
        "40g",
        "A, C",
    )


async def test_bad_arguments_reach_the_model_as_an_error_naming_the_field(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("list_menu", {"category": "SOUP"}, "call_1")], [Text("Sorry.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    (error,) = tool_messages(fake.received[1])
    assert (error.tool_call_id, error.status) == ("call_1", "error")
    assert payload(error)["error"] == "INVALID_ARGUMENTS"
    assert "category" in payload(error)["message"]


async def test_a_malformed_call_gets_an_error_tool_message_and_the_turn_goes_on(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("list_menu", "not json", "call_bad")], [Text("Sorry.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    assert isinstance(fake.received[1][2], AIMessage)
    assert [call["id"] for call in fake.received[1][2].invalid_tool_calls] == ["call_bad"]
    (error,) = tool_messages(fake.received[1])
    assert (error.tool_call_id, error.status) == ("call_bad", "error")
    assert payload(error)["error"] == "MALFORMED_CALL"


async def test_a_domain_error_in_a_tool_becomes_its_code_and_the_turn_goes_on(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("get_dish", {"dish_id": str(uuid.uuid4())}, "call_1")], [Text("None.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    (error,) = tool_messages(fake.received[1])
    assert (error.tool_call_id, error.status) == ("call_1", "error")
    assert payload(error) == {"error": "DISH_NOT_FOUND", "message": "No dish with this id exists."}


async def test_a_crashing_tool_becomes_tool_failed_and_the_exception_is_logged(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    menu: Menu,
    fake: FakeChatModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode(self: DishCatalogService, *, dish_id: uuid.UUID) -> DishView:
        raise RuntimeError("the catalog is on fire")

    monkeypatch.setattr(DishCatalogService, "get", explode)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("get_dish", {"dish_id": str(menu.cake.id)}, "call_1")], [Text("Sorry.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    (error,) = tool_messages(fake.received[1])
    assert (error.tool_call_id, error.status) == ("call_1", "error")
    assert payload(error) == {"error": "TOOL_FAILED"}
    assert [str(e) for e in logged_errors(caplog) if isinstance(e, RuntimeError)] == [
        "the catalog is on fire"
    ]


@pytest.mark.parametrize("assistant_overrides", [{"tool_result_max_chars": 200}])
async def test_a_long_tool_result_is_cut_with_a_marker(
    client: httpx2.AsyncClient, users: dict[str, User], menu: Menu, fake: FakeChatModel
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Call("list_menu", {}, "call_1")], [Text("Many.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    (result,) = tool_messages(fake.received[1])
    content = str(result.content)
    assert content.endswith(TRUNCATED)
    assert len(content) == 200 + len(TRUNCATED)
    assert content.startswith('{"total": 3')


@pytest.mark.parametrize("assistant_overrides", [{"history_messages": 20}])
async def test_the_model_sees_the_last_history_messages_with_the_new_one_last(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    fake: FakeChatModel,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    for index in range(25):
        await add_message(
            session_factory,
            session_id=session_id,
            role=USER if index % 2 == 0 else ASSISTANT,
            text=f"message {index}",
            created_at=START - (25 - index) * MINUTE,
        )
    fake.scripts = [[Text("Noted.")]]

    response = await send(client, session_id, text="message 25")

    assert response.status_code == 200, response.text
    (received,) = fake.received
    assert isinstance(received[0], SystemMessage)
    history = received[1:]
    assert [str(message.text) for message in history] == [f"message {i}" for i in range(6, 26)]
    assert [type(message) for message in history[:-1]] == [
        HumanMessage if i % 2 == 0 else AIMessage for i in range(6, 25)
    ]
    assert isinstance(history[-1], HumanMessage)


def count_pages(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    pages = [0]
    list_page: Callable[..., Any] = DishCatalogService.list_page

    async def counted(self: DishCatalogService, **kwargs: Any) -> DishPage:
        pages[0] += 1
        page: DishPage = await list_page(self, **kwargs)
        return page

    monkeypatch.setattr(DishCatalogService, "list_page", counted)
    return pages


@pytest.mark.parametrize("assistant_overrides", [{"max_rounds": 2}])
async def test_past_the_round_cap_the_fallback_text_is_streamed_and_saved(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    menu: Menu,
    fake: FakeChatModel,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = count_pages(monkeypatch)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Call("list_menu", {}, "call_1")],
        [Act(lambda: fake_clock.advance(seconds=3)), Call("list_menu", {}, "call_2")],
    ]

    events = await stream(client, session_id)

    assert events[:3] == [
        ("thinking", {}),
        ("thinking", {}),
        ("chunk", {"text": AssistantTurnService.FALLBACK_TEXT}),
    ]
    assert events[3][0] == "done"
    assert len(fake.received) == 2
    assert pages == [1]
    body = await read_session(client, session_id)
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("USER", QUESTION),
        ("ASSISTANT", AssistantTurnService.FALLBACK_TEXT),
    ]


async def test_text_streamed_in_a_tool_round_is_saved_with_the_answer(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    menu: Menu,
    fake: FakeChatModel,
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Text("Let me check. "), Call("list_menu", {}, "call_1")],
        [Act(lambda: fake_clock.advance(seconds=3)), Text("Three desserts.")],
    ]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "chunk", "thinking", "chunk", "done"]
    body = await read_session(client, session_id)
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("USER", QUESTION),
        ("ASSISTANT", "Let me check. Three desserts."),
    ]


async def test_an_empty_final_reply_is_answered_with_the_fallback_text(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel, fake_clock: FakeClock
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Act(lambda: fake_clock.advance(seconds=3))]]

    events = await stream(client, session_id)

    assert events[:2] == [("thinking", {}), ("chunk", {"text": AssistantTurnService.FALLBACK_TEXT})]
    assert events[2][0] == "done"
    body = await read_session(client, session_id)
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("USER", QUESTION),
        ("ASSISTANT", AssistantTurnService.FALLBACK_TEXT),
    ]


async def test_only_the_first_message_names_the_session(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel, fake_clock: FakeClock
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Act(lambda: fake_clock.advance(seconds=3)), Text("First answer.")],
        [Act(lambda: fake_clock.advance(seconds=3)), Text("Second answer.")],
    ]

    first = await send(client, session_id)
    fake_clock.advance(seconds=3)
    second = await send(client, session_id, text="And the soups?")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = await read_session(client, session_id)
    assert body["title"] == QUESTION[:TITLE_CHARS]
    assert [(m["role"], m["text"]) for m in body["messages"]] == [
        ("USER", QUESTION),
        ("ASSISTANT", "First answer."),
        ("USER", "And the soups?"),
        ("ASSISTANT", "Second answer."),
    ]


async def test_a_failing_final_transaction_ends_the_stream_with_a_server_error(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode(self: AssistantSessionRepository, **kwargs: Any) -> None:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(AssistantSessionRepository, "touch", explode)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello.")]]

    events = await stream(client, session_id)

    assert events[:2] == [("thinking", {}), ("chunk", {"text": "Hello."})]
    ((name, error),) = events[2:]
    assert name == "error"
    assert error["code"] == "SERVER_ERROR"
    assert [m["role"] for m in (await read_session(client, session_id))["messages"]] == ["USER"]
    assert [str(e) for e in logged_errors(caplog) if isinstance(e, RuntimeError)] == [
        "the database is gone"
    ]


def test_the_chat_model_is_built_from_the_openai_settings() -> None:
    model = build_chat_model(
        OpenAISettings(
            api_key=SecretStr("test"), model="m", max_output_tokens=7, request_timeout_seconds=3
        )
    )

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "m"
    assert model.max_tokens == 7
    assert model.request_timeout == 3
    assert model.max_retries == 1


def test_no_chat_model_is_built_without_a_key() -> None:
    assert build_chat_model(OpenAISettings()) is None


def test_the_app_builds_one_chat_model_and_every_request_gets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr("test"), model="m", max_output_tokens=7)
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    app = create_app()

    model = app.state.chat_model
    assert isinstance(model, ChatOpenAI)
    assert (model.model_name, model.max_tokens) == ("m", 7)
    request = Request({"type": "http", "app": app})
    assert get_chat_model(request) is model
    assert get_chat_model(request) is model


def test_without_a_chat_model_the_assistant_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(openai=OpenAISettings())
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()

    assert app.state.chat_model is None
    with pytest.raises(AssistantUnavailableError):
        get_chat_model(Request({"type": "http", "app": app}))


@pytest.mark.parametrize("assistant_overrides", [{"max_tool_calls": 15}])
async def test_a_round_that_would_pass_the_tool_call_cap_runs_none_of_its_calls(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    menu: Menu,
    fake: FakeChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = count_pages(monkeypatch)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Call("list_menu", {}, f"first_{n}") for n in range(10)],
        [Call("list_menu", {}, f"second_{n}") for n in range(6)],
    ]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    assert events[2] == ("chunk", {"text": AssistantTurnService.FALLBACK_TEXT})
    assert len(fake.received) == 2
    assert [m.tool_call_id for m in tool_messages(fake.received[1])] == [
        f"first_{n}" for n in range(10)
    ]
    assert pages == [10]


async def test_a_provider_failure_ends_the_stream_with_an_error_and_keeps_the_user_message(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    fake_clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("We "), Raise(RuntimeError("the provider is down"))]]
    fake_clock.advance(minutes=5)

    events = await stream(client, session_id)

    assert events[:2] == [("thinking", {}), ("chunk", {"text": "We "})]
    ((name, error),) = events[2:]
    assert name == "error"
    assert set(error) == {"code", "message"}
    assert error["code"] == "ASSISTANT_PROVIDER_ERROR"
    body = await read_session(client, session_id)
    assert [(m["role"], m["text"]) for m in body["messages"]] == [("USER", QUESTION)]
    assert moment(body["updated_at"]) == START + 5 * MINUTE
    assert [str(e) for e in logged_errors(caplog) if isinstance(e, RuntimeError)] == [
        "the provider is down"
    ]


@pytest.mark.parametrize("assistant_overrides", [{"turn_timeout_seconds": 1}])
async def test_a_turn_past_the_wall_clock_cap_ends_with_a_timeout_error(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Let me think"), Wait(30)]]

    events = await stream(client, session_id)

    assert events[:2] == [("thinking", {}), ("chunk", {"text": "Let me think"})]
    ((name, error),) = events[2:]
    assert name == "error"
    assert error["code"] == "ASSISTANT_TIMEOUT"
    assert error["message"]
    body = await read_session(client, session_id)
    assert [m["role"] for m in body["messages"]] == ["USER"]
    assert any(
        record.levelno >= logging.WARNING and "timed out" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize("text", ["", " \n\t ", "x" * 2001])
async def test_an_empty_or_too_long_text_is_a_validation_error(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel, text: str
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)

    response = await send(client, session_id, text=text)

    assert_error(response, 422, "VALIDATION_ERROR")
    assert response.json()["details"][0]["field"] == "text"
    assert fake.received == []
    assert (await read_session(client, session_id))["messages"] == []


async def test_another_users_or_an_unknown_session_is_not_found(
    client: httpx2.AsyncClient, users: dict[str, User], fake: FakeChatModel
) -> None:
    await sign_in(client, GRACE)
    foreign = await create_session(client)
    await sign_in(client, ADA)

    for session_id in (foreign, str(uuid.uuid4())):
        response = await send(client, session_id)

        assert_error(response, 404, "ASSISTANT_SESSION_NOT_FOUND")
    assert fake.received == []
