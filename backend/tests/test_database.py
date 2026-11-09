from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import func, inspect, select, text
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
        "failed_login_attempts": False,
        "login_locked_until": True,
        "created_at": False,
        "updated_at": False,
    }


async def test_new_users_start_with_no_failed_login_attempts(
    session_factory: async_sessionmaker[AsyncSession], connection: AsyncConnection
) -> None:
    async with session_scope() as session:
        session.add(User(first_name="Ada", last_name="Lovelace", email="ada@example.com"))

    user = (await connection.execute(select(User).where(User.email == "ada@example.com"))).one()
    assert user.failed_login_attempts == 0
    assert user.login_locked_until is None


async def test_migrated_refresh_tokens_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("refresh_tokens"),
            "foreign_keys": inspector.get_foreign_keys("refresh_tokens"),
            "unique": inspector.get_unique_constraints("refresh_tokens"),
            "indexes": inspector.get_indexes("refresh_tokens"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "user_id": False,
        "token_hash": False,
        "expires_at": False,
        "revoked_at": True,
        "rotated_at": True,
        "created_at": False,
    }
    [foreign_key] = shape["foreign_keys"]
    assert foreign_key["constrained_columns"] == ["user_id"]
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert [constraint["column_names"] for constraint in shape["unique"]] == [["token_hash"]]
    # PostgreSQL backs the unique constraint with an index of its own.
    indexes = [index for index in shape["indexes"] if not index.get("duplicates_constraint")]
    assert [index["column_names"] for index in indexes] == [["user_id"]]


async def test_verification_purpose_enum_has_both_labels(connection: AsyncConnection) -> None:
    labels = await connection.scalar(text("SELECT enum_range(NULL::verification_purpose)::text[]"))

    assert labels == ["EMAIL_VERIFICATION", "PASSWORD_RESET"]


async def test_migrated_verification_codes_table_has_the_index_and_cascading_fk(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "foreign_keys": inspector.get_foreign_keys("verification_codes"),
            "indexes": inspector.get_indexes("verification_codes"),
        }

    shape = await connection.run_sync(describe)

    [foreign_key] = shape["foreign_keys"]
    assert foreign_key["name"] == "fk_verification_codes_user_id_users"
    assert foreign_key["constrained_columns"] == ["user_id"]
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert [(index["name"], index["column_names"]) for index in shape["indexes"]] == [
        ("ix_verification_codes_user_id_purpose_created_at", ["user_id", "purpose", "created_at"])
    ]
