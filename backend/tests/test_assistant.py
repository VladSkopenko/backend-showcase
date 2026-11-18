import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    GRACE,
    START,
    FakeClock,
    add_guest,
    as_guest,
    assert_error,
    sign_in,
)

from app.config.settings import OpenAISettings, Settings, get_settings
from app.features.assistant.enums import AssistantMessageRole
from app.features.core.health.endpoints.dependencies import get_database_engine
from app.main import create_app
from app.model_registry import AssistantMessage, AssistantSession, User

pytestmark = pytest.mark.anyio

SESSIONS = "/api/v1/assistant/sessions"
NEW_CHAT = "New chat"
MINUTE = timedelta(minutes=1)
USER = AssistantMessageRole.USER
ASSISTANT = AssistantMessageRole.ASSISTANT


@pytest.fixture
def api_key() -> str:
    return "test"


@pytest.fixture
def app(api_key: str) -> FastAPI:
    app = create_app()
    settings = Settings(openai=OpenAISettings(api_key=SecretStr(api_key)))
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


async def create_session(client: httpx2.AsyncClient) -> dict[str, Any]:
    response = await client.post(SESSIONS)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def add_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    role: AssistantMessageRole,
    text: str,
    created_at: datetime,
) -> uuid.UUID:
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
    return message.id


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def action_routes() -> list[tuple[str, str]]:
    action = f"{SESSIONS}/{uuid.uuid4()}/actions/{uuid.uuid4()}"
    return [("GET", action), ("POST", f"{action}/cancel"), ("POST", f"{action}/apply")]


async def request(
    client: httpx2.AsyncClient, method: str, path: str, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return await client.request(method, path, headers=headers)


async def test_a_verified_user_creates_sessions_and_lists_them_latest_activity_first(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    await sign_in(client, ADA)
    first = await create_session(client)
    fake_clock.advance(minutes=1)
    second = await create_session(client)
    assert set(first) == {"id", "title", "created_at", "updated_at"}
    assert first["title"] == NEW_CHAT
    assert moment(first["created_at"]) == moment(first["updated_at"]) == START
    assert moment(second["created_at"]) == START + MINUTE
    await add_message(
        session_factory,
        session_id=first["id"],
        role=USER,
        text="What is in the khachapuri?",
        created_at=START + 2 * MINUTE,
    )

    response = await client.get(SESSIONS)

    assert response.status_code == 200, response.text
    sessions = response.json()
    assert [session["id"] for session in sessions] == [first["id"], second["id"]]
    assert set(sessions[0]) == {"id", "title", "created_at", "updated_at"}
    assert moment(sessions[0]["updated_at"]) == START + 2 * MINUTE
    assert sessions[1] == second


async def test_a_session_reads_back_with_its_messages_oldest_first(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    created = await create_session(client)
    question = await add_message(
        session_factory,
        session_id=created["id"],
        role=USER,
        text="What is in the khachapuri?",
        created_at=START + MINUTE,
    )
    answer = await add_message(
        session_factory,
        session_id=created["id"],
        role=ASSISTANT,
        text="Cheese, eggs and butter in a bread boat.",
        created_at=START + 2 * MINUTE,
    )

    response = await client.get(f"{SESSIONS}/{created['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "title", "created_at", "updated_at", "messages"}
    assert body["id"] == created["id"]
    assert body["title"] == NEW_CHAT
    assert moment(body["created_at"]) == START
    assert moment(body["updated_at"]) == START + 2 * MINUTE
    assert [set(message) for message in body["messages"]] == [
        {"id", "role", "text", "created_at", "action"}
    ] * 2
    assert [message["action"] for message in body["messages"]] == [None, None]
    assert [(m["id"], m["role"], m["text"], moment(m["created_at"])) for m in body["messages"]] == [
        (str(question), "USER", "What is in the khachapuri?", START + MINUTE),
        (str(answer), "ASSISTANT", "Cheese, eggs and butter in a bread boat.", START + 2 * MINUTE),
    ]


async def test_an_unverified_user_is_refused(
    client: httpx2.AsyncClient, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    await connection.execute(update(User).where(User.email == ADA).values(email_verified_at=None))

    responses = [
        await client.post(SESSIONS),
        await client.get(SESSIONS),
        await client.get(f"{SESSIONS}/{uuid.uuid4()}"),
        await client.post(f"{SESSIONS}/{uuid.uuid4()}/messages", json={"text": "hi"}),
        *[await request(client, method, path) for method, path in action_routes()],
    ]

    for response in responses:
        assert_error(response, 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("guest", [False, True])
async def test_a_guest_or_nobody_is_refused(
    client: httpx2.AsyncClient, session_factory: async_sessionmaker[AsyncSession], guest: bool
) -> None:
    headers: dict[str, str] = {}
    if guest:
        await add_guest(session_factory, name="Linus", token="guest-secret")
        headers = as_guest("guest-secret")

    responses = [
        await client.post(SESSIONS, headers=headers),
        await client.get(SESSIONS, headers=headers),
        await client.get(f"{SESSIONS}/{uuid.uuid4()}", headers=headers),
        await client.post(
            f"{SESSIONS}/{uuid.uuid4()}/messages", json={"text": "hi"}, headers=headers
        ),
        *[await request(client, method, path, headers) for method, path in action_routes()],
    ]

    for response in responses:
        assert_error(response, 401, "NOT_AUTHENTICATED")


@pytest.mark.parametrize("api_key", [""])
async def test_without_a_key_every_assistant_route_is_unavailable_and_the_rest_runs(
    app: FastAPI, client: httpx2.AsyncClient, users: dict[str, User], engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_database_engine] = lambda: engine
    anonymous = await client.get(SESSIONS)
    await sign_in(client, ADA)

    responses = [
        anonymous,
        await client.post(SESSIONS),
        await client.get(SESSIONS),
        await client.get(f"{SESSIONS}/{uuid.uuid4()}"),
        await client.post(f"{SESSIONS}/{uuid.uuid4()}/messages", json={"text": "hi"}),
        *[await request(client, method, path) for method, path in action_routes()],
    ]

    for response in responses:
        assert_error(response, 503, "ASSISTANT_UNAVAILABLE")
    assert (await client.get("/health")).status_code == 200


async def test_a_session_id_that_is_not_a_uuid_is_a_validation_error(
    client: httpx2.AsyncClient, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)

    response = await client.get(f"{SESSIONS}/not-a-uuid")

    assert_error(response, 422, "VALIDATION_ERROR")


async def test_another_users_or_an_unknown_session_is_not_found(
    client: httpx2.AsyncClient, users: dict[str, User]
) -> None:
    await sign_in(client, GRACE)
    foreign = await create_session(client)
    await sign_in(client, ADA)

    for session_id in (foreign["id"], str(uuid.uuid4())):
        response = await client.get(f"{SESSIONS}/{session_id}")

        assert_error(response, 404, "ASSISTANT_SESSION_NOT_FOUND")
    assert (await client.get(SESSIONS)).json() == []
