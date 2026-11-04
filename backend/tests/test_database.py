from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common.database import get_session
from app.model_registry import User

pytestmark = pytest.mark.anyio

session_scope = asynccontextmanager(get_session)


async def count_users(connection: AsyncConnection, email: str) -> int:
    count = await connection.scalar(
        select(func.count()).select_from(User).where(User.email == email)
    )
    assert count is not None
    return count


async def test_get_session_commits_when_the_body_returns(
    session_factory: async_sessionmaker[AsyncSession], connection: AsyncConnection
) -> None:
    async with session_scope() as session:
        session.add(User(first_name="Ada", last_name="Lovelace", email="ada@example.com"))

    assert await count_users(connection, "ada@example.com") == 1


async def test_get_session_rolls_back_and_reraises_when_the_body_raises(
    session_factory: async_sessionmaker[AsyncSession], connection: AsyncConnection
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with session_scope() as session:
            session.add(User(first_name="Ada", last_name="Lovelace", email="ada@example.com"))
            await session.flush()
            raise RuntimeError("boom")

    assert await count_users(connection, "ada@example.com") == 0


async def test_duplicate_email_fails_on_the_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(User(first_name="Ada", last_name="Lovelace", email="dup@example.com"))
        await session.flush()
        session.add(User(first_name="Grace", last_name="Hopper", email="dup@example.com"))

        with pytest.raises(IntegrityError, match="uq_users_email"):
            await session.flush()


async def test_migrated_users_table_has_the_expected_columns(
    connection: AsyncConnection,
) -> None:
    def get_columns(sync_connection: Connection) -> list[Any]:
        return inspect(sync_connection).get_columns("users")

    columns = await connection.run_sync(get_columns)

    assert {column["name"]: column["nullable"] for column in columns} == {
        "id": False,
        "first_name": False,
        "last_name": False,
        "email": False,
        "password_hash": True,
        "email_verified_at": True,
        "created_at": False,
        "updated_at": False,
    }
