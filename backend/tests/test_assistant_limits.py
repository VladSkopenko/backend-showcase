import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from langchain_core.messages.ai import InputTokenDetails, UsageMetadata
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from support.bookings import ADA, GRACE, START, TODAY, TZ, FakeClock, assert_error, at, sign_in
from support.fake_chat_model import Call, FakeChatModel, Raise, Text, Usage
from support.sse import parse_events

from app.config.settings import AssistantSettings, OpenAISettings, Settings, get_settings
from app.features.assistant.dto import ModelPrices
from app.features.assistant.endpoints.dependencies import get_chat_model
from app.features.assistant.enums import AssistantMessageRole
from app.features.assistant.services.usage_ledger import UsageLedger
from app.main import create_app
from app.model_registry import AssistantMessage, AssistantModelCall, AssistantSession, User

pytestmark = pytest.mark.anyio

SESSIONS = "/api/v1/assistant/sessions"
QUESTION = "What desserts do you have?"
MODEL = "gpt-4.1-mini"
MICRO_USD = 1_000_000
LOCAL_MIDNIGHT = at(TODAY, 0)
NEXT_LOCAL_MIDNIGHT = at(TODAY + timedelta(days=1), 0)


@pytest.fixture
def api_key() -> str:
    return "test"


@pytest.fixture
def assistant_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
def fake() -> FakeChatModel:
    return FakeChatModel(scripts=[])


@pytest.fixture
def app(fake: FakeChatModel, api_key: str, assistant_overrides: dict[str, Any]) -> FastAPI:
    app = create_app()
    settings = Settings(
        openai=OpenAISettings(api_key=SecretStr(api_key), model=MODEL),
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


async def create_session(client: httpx2.AsyncClient) -> str:
    response = await client.post(SESSIONS)
    assert response.status_code == 201, response.text
    session_id: str = response.json()["id"]
    return session_id


async def send(client: httpx2.AsyncClient, session_id: str) -> httpx2.Response:
    return await client.post(f"{SESSIONS}/{session_id}/messages", json={"text": QUESTION})


async def stream(client: httpx2.AsyncClient, session_id: str) -> list[tuple[str, Any]]:
    response = await send(client, session_id)
    assert response.status_code == 200, response.text
    return parse_events(response.text)


async def add_model_call(
    session_factory: async_sessionmaker[AsyncSession], *, cost_micro_usd: int, created_at: datetime
) -> None:
    async with session_factory() as session:
        session.add(
            AssistantModelCall(
                model=MODEL,
                input_tokens=1000,
                cached_input_tokens=0,
                output_tokens=100,
                cost_micro_usd=cost_micro_usd,
                created_at=created_at,
            )
        )
        await session.commit()


async def add_user_messages(
    session_factory: async_sessionmaker[AsyncSession], *, user: User, created_at: list[datetime]
) -> None:
    async with session_factory() as session:
        chat_session = AssistantSession(
            user_id=user.id, title="Earlier", created_at=START, updated_at=START
        )
        session.add(chat_session)
        await session.flush()
        session.add_all(
            AssistantMessage(
                session_id=chat_session.id,
                role=AssistantMessageRole.USER,
                text="Earlier question",
                created_at=moment,
            )
            for moment in created_at
        )
        await session.commit()


async def model_calls(session_factory: async_sessionmaker[AsyncSession]) -> list[tuple[Any, ...]]:
    async with session_factory() as session:
        rows = await session.execute(
            select(
                AssistantModelCall.model,
                AssistantModelCall.input_tokens,
                AssistantModelCall.cached_input_tokens,
                AssistantModelCall.output_tokens,
                AssistantModelCall.cost_micro_usd,
            ).order_by(AssistantModelCall.created_at, AssistantModelCall.input_tokens)
        )
        return [tuple(row) for row in rows]


async def messages_of(
    session_factory: async_sessionmaker[AsyncSession], session_id: str
) -> list[AssistantMessageRole]:
    async with session_factory() as session:
        roles = await session.scalars(
            select(AssistantMessage.role).where(
                AssistantMessage.session_id == uuid.UUID(session_id)
            )
        )
        return list(roles)


async def test_every_model_call_records_its_usage_and_cost(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Call("list_menu", {"category": "DESSERT"}, "call_1"), Usage(1000, 200, 50)],
        [Text("Three desserts."), Usage(3000, 1000, 120)],
    ]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "thinking", "chunk", "done"]
    assert await model_calls(session_factory) == [
        (MODEL, 1000, 200, 50, 420),
        (MODEL, 3000, 1000, 120, 1092),
    ]


async def test_the_cost_is_the_tokens_times_the_prices_per_million(
    session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> None:
    prices = ModelPrices(
        input_per_million_usd=Decimal("0.40"),
        cached_input_per_million_usd=Decimal("0.10"),
        output_per_million_usd=Decimal("1.60"),
    )
    usage = UsageMetadata(
        input_tokens=1000,
        output_tokens=50,
        total_tokens=1050,
        input_token_details=InputTokenDetails(cache_read=200),
    )

    async with session_factory() as session:
        ledger = UsageLedger(
            session,
            prices=prices,
            timezone=TZ,
            daily_budget_usd=Decimal("1.0"),
            turns_per_minute=10,
        )
        await ledger.record(usage=usage, model=MODEL)
        await session.commit()

    assert await model_calls(session_factory) == [(MODEL, 1000, 200, 50, 420)]
    async with session_factory() as session:
        created_at = await session.scalar(select(AssistantModelCall.created_at))
    assert created_at == START


async def test_once_todays_spend_reaches_the_budget_a_turn_is_refused_until_local_midnight(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_model_call(
        session_factory, cost_micro_usd=600_000, created_at=LOCAL_MIDNIGHT + timedelta(minutes=30)
    )
    await add_model_call(session_factory, cost_micro_usd=400_000, created_at=START)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello.")]]

    response = await send(client, session_id)

    assert_error(response, 429, "ASSISTANT_BUDGET_EXHAUSTED")
    retry_after = int((NEXT_LOCAL_MIDNIGHT - START).total_seconds())
    assert retry_after == 10 * 3600 + 50 * 60
    assert response.json()["retry_after"] == retry_after
    assert response.headers["retry-after"] == str(retry_after)
    assert fake.received == []
    assert await messages_of(session_factory, session_id) == []


async def test_yesterdays_spend_does_not_count_toward_todays_budget(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_model_call(
        session_factory,
        cost_micro_usd=5 * MICRO_USD,
        created_at=LOCAL_MIDNIGHT - timedelta(seconds=1),
    )
    await add_model_call(session_factory, cost_micro_usd=MICRO_USD - 1, created_at=START)
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "chunk", "done"]


async def test_a_call_cut_off_before_its_usage_records_nothing_and_finished_calls_stay(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [
        [Call("list_menu", {}, "call_1"), Usage(1000, 200, 50)],
        [Text("We "), Raise(RuntimeError("the provider is down")), Usage(900, 0, 10)],
    ]

    events = await stream(client, session_id)

    name, error = events[-1]
    assert name == "error"
    assert error["code"] == "ASSISTANT_PROVIDER_ERROR"
    assert await model_calls(session_factory) == [(MODEL, 1000, 200, 50, 420)]


@pytest.mark.parametrize("assistant_overrides", [{"turns_per_minute": 2}])
async def test_too_many_turns_in_the_last_minute_make_the_assistant_busy(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_user_messages(
        session_factory,
        user=users[GRACE],
        created_at=[START - timedelta(seconds=59), START - timedelta(seconds=10)],
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello.")]]

    response = await send(client, session_id)

    assert_error(response, 429, "ASSISTANT_BUSY")
    assert response.json()["retry_after"] == 1
    assert response.headers["retry-after"] == "1"
    assert fake.received == []
    assert await messages_of(session_factory, session_id) == []


async def test_a_usage_without_cached_tokens_records_none_cached(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello."), Usage(1000, None, 50)]]

    await stream(client, session_id)

    assert await model_calls(session_factory) == [(MODEL, 1000, 0, 50, 480)]


@pytest.mark.parametrize("assistant_overrides", [{"turns_per_minute": 2}])
async def test_past_the_cap_the_wait_counts_from_the_oldest_of_the_latest_counted_turns(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_user_messages(
        session_factory,
        user=users[GRACE],
        created_at=[
            START - timedelta(seconds=50),
            START - timedelta(seconds=30),
            START - timedelta(seconds=10),
        ],
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)

    response = await send(client, session_id)

    assert_error(response, 429, "ASSISTANT_BUSY")
    assert response.json()["retry_after"] == 30
    assert response.headers["retry-after"] == "30"


@pytest.mark.parametrize("assistant_overrides", [{"turns_per_minute": 2}])
async def test_a_message_older_than_a_minute_no_longer_counts(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_user_messages(
        session_factory,
        user=users[GRACE],
        created_at=[START - timedelta(seconds=61), START - timedelta(seconds=10)],
    )
    await sign_in(client, ADA)
    session_id = await create_session(client)
    fake.scripts = [[Text("Hello.")]]

    events = await stream(client, session_id)

    assert [name for name, _ in events] == ["thinking", "chunk", "done"]


@pytest.mark.parametrize("api_key", [""])
async def test_without_a_key_the_turn_is_unavailable_before_the_budget_is_read(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    fake: FakeChatModel,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_model_call(session_factory, cost_micro_usd=5 * MICRO_USD, created_at=START)
    checks: list[datetime] = []

    async def spy(self: UsageLedger, *, now: datetime) -> None:
        checks.append(now)

    monkeypatch.setattr(UsageLedger, "check", spy)
    await sign_in(client, ADA)

    response = await client.post(f"{SESSIONS}/{uuid.uuid4()}/messages", json={"text": QUESTION})

    assert_error(response, 503, "ASSISTANT_UNAVAILABLE")
    assert checks == []
    assert fake.received == []
