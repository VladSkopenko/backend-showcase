import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import ADA, GRACE, LOGIN, PASSWORD, START, FakeClock
from support.http import set_cookies

from app.config.settings import Settings, get_settings
from app.features.assistant.enums import AssistantMessageRole
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.repositories import VerificationCodeRepository
from app.infrastructure.background_tasks import CleanupJob, RequestExpiryJob
from app.main import create_app
from app.model_registry import (
    AssistantMessage,
    AssistantSession,
    RefreshToken,
    User,
    VerificationCode,
)

pytestmark = pytest.mark.anyio

AUTH = "/api/v1/auth"
DAY = timedelta(days=1)
CODE_TTL = timedelta(minutes=10)
SESSION_TTL_DAYS = 7
JOB_LOGGER = "app.infrastructure.background_tasks.cleanup_job"
EMAIL = VerificationPurpose.EMAIL_VERIFICATION
RESET = VerificationPurpose.PASSWORD_RESET


@pytest.fixture
def job(session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock) -> CleanupJob:
    return CleanupJob(session_factory, assistant_session_ttl_days=SESSION_TTL_DAYS)


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


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def add_token(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    expires_at: datetime,
    revoked: bool = False,
    rotated: bool = False,
) -> uuid.UUID:
    created_at = expires_at - timedelta(days=30)
    token = RefreshToken(
        user_id=user.id,
        token_hash=sha256(str(uuid.uuid4())),
        created_at=created_at,
        expires_at=expires_at,
        revoked_at=created_at if revoked or rotated else None,
        rotated_at=created_at if rotated else None,
    )
    async with session_factory() as session:
        session.add(token)
        await session.commit()
    return token.id


async def add_code(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    created_at: datetime,
    purpose: VerificationPurpose = EMAIL,
    expires_at: datetime | None = None,
    consumed: bool = False,
    plain_code: str = "123456",
) -> uuid.UUID:
    code = VerificationCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=sha256(plain_code),
        created_at=created_at,
        expires_at=created_at + CODE_TTL if expires_at is None else expires_at,
        consumed_at=created_at + timedelta(minutes=1) if consumed else None,
    )
    async with session_factory() as session:
        session.add(code)
        await session.commit()
    return code.id


async def add_session(
    session_factory: async_sessionmaker[AsyncSession], *, user: User, updated_at: datetime
) -> tuple[uuid.UUID, uuid.UUID]:
    chat = AssistantSession(
        user_id=user.id, title="New chat", created_at=updated_at - DAY, updated_at=updated_at
    )
    async with session_factory() as session:
        session.add(chat)
        await session.flush()
        message = AssistantMessage(
            session_id=chat.id,
            role=AssistantMessageRole.USER,
            text="Hello",
            created_at=updated_at,
        )
        session.add(message)
        await session.commit()
    return chat.id, message.id


async def token_ids(connection: AsyncConnection) -> set[uuid.UUID]:
    return set((await connection.scalars(select(RefreshToken.id))).all())


async def session_ids(connection: AsyncConnection) -> set[uuid.UUID]:
    return set((await connection.scalars(select(AssistantSession.id))).all())


async def message_ids(connection: AsyncConnection) -> set[uuid.UUID]:
    return set((await connection.scalars(select(AssistantMessage.id))).all())


async def code_ids(connection: AsyncConnection) -> set[uuid.UUID]:
    return set((await connection.scalars(select(VerificationCode.id))).all())


async def tokens_of(connection: AsyncConnection, user: User) -> list[Any]:
    rows = await connection.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    return list(rows.all())


def info_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == JOB_LOGGER and record.levelno == logging.INFO
    ]


async def log_in(client: httpx2.AsyncClient, email: str) -> str:
    client.cookies.clear()
    response = await client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return set_cookies(response)["refresh_token"]["value"]


async def refresh_with(client: httpx2.AsyncClient, token: str) -> httpx2.Response:
    client.cookies.clear()
    return await client.post(f"{AUTH}/refresh", headers={"Cookie": f"refresh_token={token}"})


async def test_expired_tokens_are_deleted_whatever_their_state(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    for state in ({}, {"revoked": True}, {"rotated": True}):
        await add_token(
            session_factory, user=users[ADA], expires_at=START - timedelta(minutes=1), **state
        )

    await job.run()

    assert await token_ids(connection) == set()


async def test_live_tokens_are_kept_whatever_their_state(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    kept = {
        await add_token(
            session_factory, user=users[ADA], expires_at=START + timedelta(seconds=1), **state
        )
        for state in ({}, {"revoked": True}, {"rotated": True})
    }

    await job.run()

    assert await token_ids(connection) == kept


async def test_a_token_expiring_exactly_now_is_deleted(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_token(session_factory, user=users[ADA], expires_at=START)

    await job.run()

    assert await token_ids(connection) == set()


async def test_a_live_rotated_token_presented_after_a_run_still_revokes_every_session(
    job: CleanupJob,
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    expired = await add_token(
        session_factory, user=users[ADA], expires_at=START - timedelta(minutes=1)
    )
    stolen = await log_in(client, ADA)
    assert (await client.post(f"{AUTH}/refresh")).status_code == 204
    fake_clock.advance(minutes=1)
    await job.run()
    assert expired not in await token_ids(connection)

    response = await refresh_with(client, stolen)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    tokens = await tokens_of(connection, users[ADA])
    assert len(tokens) == 2
    assert all(token.revoked_at is not None for token in tokens)


async def test_an_expired_rotated_token_presented_after_a_run_leaves_other_sessions_alone(
    job: CleanupJob,
    client: httpx2.AsyncClient,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    stolen = await log_in(client, ADA)
    assert (await client.post(f"{AUTH}/refresh")).status_code == 204
    fake_clock.advance(days=30, minutes=1)
    current = await log_in(client, ADA)
    await job.run()

    response = await refresh_with(client, stolen)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    tokens = await tokens_of(connection, users[ADA])
    assert [token.token_hash for token in tokens] == [sha256(current)]
    assert tokens[0].revoked_at is None


async def test_logout_with_an_expired_rotated_token_after_a_run_leaves_other_sessions_alone(
    job: CleanupJob,
    client: httpx2.AsyncClient,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    stolen = await log_in(client, ADA)
    assert (await client.post(f"{AUTH}/refresh")).status_code == 204
    fake_clock.advance(days=30, minutes=1)
    current = await log_in(client, ADA)
    await job.run()
    client.cookies.clear()

    response = await client.post(f"{AUTH}/logout", headers={"Cookie": f"refresh_token={stolen}"})

    assert response.status_code == 204
    tokens = await tokens_of(connection, users[ADA])
    assert [token.token_hash for token in tokens] == [sha256(current)]
    assert tokens[0].revoked_at is None


async def test_old_expired_codes_with_a_newer_code_are_deleted_consumed_or_not(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    for purpose in (EMAIL, RESET):
        await add_code(
            session_factory, user=users[ADA], purpose=purpose, created_at=START - 3 * DAY
        )
        await add_code(
            session_factory,
            user=users[ADA],
            purpose=purpose,
            created_at=START - 2 * DAY,
            consumed=True,
        )
    newest = {
        await add_code(session_factory, user=users[ADA], purpose=purpose, created_at=START)
        for purpose in (EMAIL, RESET)
    }

    await job.run()

    assert await code_ids(connection) == newest


async def test_the_newest_code_of_a_user_and_purpose_is_kept_and_still_answers_code_expired(
    job: CleanupJob,
    client: httpx2.AsyncClient,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    kept = {
        await add_code(
            session_factory,
            user=users[ADA],
            purpose=RESET,
            created_at=START - 2 * DAY,
            plain_code="654321",
        ),
        # Newer codes of another purpose or another user do not replace it.
        await add_code(session_factory, user=users[ADA], purpose=EMAIL, created_at=START),
        await add_code(session_factory, user=users[GRACE], purpose=RESET, created_at=START),
    }

    await job.run()

    assert await code_ids(connection) == kept
    response = await client.post(
        f"{AUTH}/password-reset/verify-code", json={"email": ADA, "code": "654321"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CODE_EXPIRED"


async def test_recent_and_unexpired_codes_are_kept_even_with_a_newer_code(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    kept = {
        await add_code(
            session_factory, user=users[ADA], created_at=START - DAY + timedelta(seconds=1)
        ),
        await add_code(
            session_factory,
            user=users[ADA],
            created_at=START - 2 * DAY,
            expires_at=START + timedelta(seconds=1),
        ),
        await add_code(session_factory, user=users[ADA], created_at=START),
    }

    await job.run()

    assert await code_ids(connection) == kept


async def test_an_expired_code_created_exactly_a_day_ago_with_a_newer_code_is_deleted(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_code(session_factory, user=users[ADA], created_at=START - DAY)
    newest = await add_code(session_factory, user=users[ADA], created_at=START)

    await job.run()

    assert await code_ids(connection) == {newest}


async def test_an_expired_code_expiring_exactly_now_with_a_newer_code_is_deleted(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_code(session_factory, user=users[ADA], created_at=START - DAY, expires_at=START)
    newest = await add_code(session_factory, user=users[ADA], created_at=START)

    await job.run()

    assert await code_ids(connection) == {newest}


async def test_two_codes_of_a_user_and_purpose_created_at_the_same_moment_both_stay(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    kept = {
        await add_code(session_factory, user=users[ADA], created_at=START - 2 * DAY)
        for _ in range(2)
    }

    await job.run()

    assert await code_ids(connection) == kept


async def test_a_run_that_deletes_rows_logs_three_counts_and_an_empty_run_logs_nothing(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    for _ in range(3):
        await add_token(session_factory, user=users[ADA], expires_at=START - DAY)
    for days in (4, 3, 2):
        await add_code(session_factory, user=users[ADA], created_at=START - days * DAY)

    with caplog.at_level(logging.INFO, logger=JOB_LOGGER):
        await job.run()
        await job.run()

    assert info_lines(caplog) == [
        "Deleted 3 expired refresh tokens, 2 old verification codes "
        "and 0 inactive assistant sessions"
    ]


async def test_sessions_inactive_for_the_ttl_are_deleted_with_their_messages_and_newer_kept(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_session(session_factory, user=users[ADA], updated_at=START - SESSION_TTL_DAYS * DAY)
    kept, kept_message = await add_session(
        session_factory, user=users[GRACE], updated_at=START - (SESSION_TTL_DAYS - 1) * DAY
    )

    with caplog.at_level(logging.INFO, logger=JOB_LOGGER):
        await job.run()

    assert await session_ids(connection) == {kept}
    assert await message_ids(connection) == {kept_message}
    assert info_lines(caplog) == [
        "Deleted 0 expired refresh tokens, 0 old verification codes "
        "and 1 inactive assistant sessions"
    ]


async def test_a_failing_run_is_rolled_back_and_the_next_run_works(
    job: CleanupJob,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = await add_token(session_factory, user=users[ADA], expires_at=START - DAY)
    await add_code(session_factory, user=users[ADA], created_at=START - 2 * DAY)
    newest = await add_code(session_factory, user=users[ADA], created_at=START)
    original_delete = VerificationCodeRepository.delete_superseded
    calls: list[None] = []

    async def fail_once(self: VerificationCodeRepository, **kwargs: Any) -> int:
        calls.append(None)
        if len(calls) == 1:
            raise ConnectionError("database went away")
        return await original_delete(self, **kwargs)

    monkeypatch.setattr(VerificationCodeRepository, "delete_superseded", fail_once)

    with pytest.raises(ConnectionError):
        await job.run()
    assert await token_ids(connection) == {expired}

    await job.run()

    assert await token_ids(connection) == set()
    assert await code_ids(connection) == {newest}


async def test_the_app_lifespan_starts_and_stops_the_cleanup_and_request_expiry_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_started = asyncio.Event()
    request_expiry_started = asyncio.Event()

    async def fake_cleanup(self: CleanupJob) -> None:
        cleanup_started.set()

    async def fake_request_expiry(self: RequestExpiryJob) -> None:
        request_expiry_started.set()

    monkeypatch.setattr(CleanupJob, "run", fake_cleanup)
    monkeypatch.setattr(RequestExpiryJob, "run", fake_request_expiry)
    app = create_app()
    names = {"cleanup", "request expiry"}

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(cleanup_started.wait(), timeout=5)
        await asyncio.wait_for(request_expiry_started.wait(), timeout=5)
        assert {t.get_name() for t in asyncio.all_tasks()} >= names

    assert not [t for t in asyncio.all_tasks() if t.get_name() in names]
