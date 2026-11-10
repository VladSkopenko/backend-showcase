from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common.database import get_session
from app.features.core.auth.enums import OAuthProvider
from app.model_registry import DiningTable, Location, OAuthAccount, User

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


async def test_migrated_user_oauth_accounts_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("user_oauth_accounts"),
            "foreign_keys": inspector.get_foreign_keys("user_oauth_accounts"),
            "unique": inspector.get_unique_constraints("user_oauth_accounts"),
            "indexes": inspector.get_indexes("user_oauth_accounts"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "user_id": False,
        "provider": False,
        "subject": False,
        "created_at": False,
    }
    [foreign_key] = shape["foreign_keys"]
    assert foreign_key["constrained_columns"] == ["user_id"]
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert sorted(
        (constraint["name"], constraint["column_names"]) for constraint in shape["unique"]
    ) == [
        ("uq_user_oauth_accounts_provider_subject", ["provider", "subject"]),
        ("uq_user_oauth_accounts_user_id_provider", ["user_id", "provider"]),
    ]
    indexes = [index for index in shape["indexes"] if not index.get("duplicates_constraint")]
    assert [(index["name"], index["column_names"]) for index in indexes] == [
        ("ix_user_oauth_accounts_user_id", ["user_id"])
    ]


async def test_oauth_provider_enum_has_google(connection: AsyncConnection) -> None:
    labels = await connection.scalar(text("SELECT enum_range(NULL::oauth_provider)::text[]"))

    assert labels == ["GOOGLE"]


@pytest.mark.parametrize(
    ("second_user_email", "second_subject", "constraint"),
    [
        ("grace@example.com", "google-sub", "uq_user_oauth_accounts_provider_subject"),
        (None, "other-sub", "uq_user_oauth_accounts_user_id_provider"),
    ],
)
async def test_oauth_account_unique_constraints(
    session_factory: async_sessionmaker[AsyncSession],
    second_user_email: str | None,
    second_subject: str,
    constraint: str,
) -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    async with session_factory() as session:
        ada = User(first_name="Ada", last_name="Lovelace", email="ada@example.com")
        session.add(ada)
        await session.flush()
        owner = ada
        if second_user_email is not None:
            owner = User(first_name="Grace", last_name="Hopper", email=second_user_email)
            session.add(owner)
            await session.flush()
        session.add(
            OAuthAccount(
                user_id=ada.id, provider=OAuthProvider.GOOGLE, subject="google-sub", created_at=now
            )
        )
        await session.flush()
        session.add(
            OAuthAccount(
                user_id=owner.id,
                provider=OAuthProvider.GOOGLE,
                subject=second_subject,
                created_at=now,
            )
        )

        with pytest.raises(IntegrityError, match=constraint):
            await session.flush()


async def test_migrated_dishes_table_has_the_expected_shape(connection: AsyncConnection) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("dishes"),
            "unique": inspector.get_unique_constraints("dishes"),
            "indexes": inspector.get_indexes("dishes"),
            "checks": inspector.get_check_constraints("dishes"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "slug": False,
        "name": False,
        "description": False,
        "category": False,
        "price_cents": False,
        "weight_grams": False,
        "calories": False,
        "protein": False,
        "fats": False,
        "carbs": False,
        "vitamins": False,
        "is_available": False,
        "popularity": False,
        "image_key": False,
        "created_at": False,
        "updated_at": False,
    }
    assert [(c["name"], c["column_names"]) for c in shape["unique"]] == [
        ("uq_dishes_slug", ["slug"])
    ]
    indexes = [index for index in shape["indexes"] if not index.get("duplicates_constraint")]
    assert sorted((index["name"], index["column_names"]) for index in indexes) == [
        ("ix_dishes_category_popularity", ["category", "popularity"]),
        ("ix_dishes_created_at", ["created_at"]),
        ("ix_dishes_popularity", ["popularity"]),
        ("ix_dishes_price_cents", ["price_cents"]),
    ]
    assert sorted(check["name"] for check in shape["checks"]) == [
        "ck_dishes_calories_non_negative",
        "ck_dishes_popularity_non_negative",
        "ck_dishes_price_cents_positive",
        "ck_dishes_weight_grams_positive",
    ]


async def test_dish_category_enum_has_the_three_menu_tabs(connection: AsyncConnection) -> None:
    labels = await connection.scalar(text("SELECT enum_range(NULL::dish_category)::text[]"))

    assert labels == ["APPETIZER", "MAIN_COURSE", "DESSERT"]


async def test_migrated_locations_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("locations"),
            "unique": inspector.get_unique_constraints("locations"),
            "indexes": inspector.get_indexes("locations"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "slug": False,
        "address": False,
        "description": False,
        "image_key": False,
        "created_at": False,
        "updated_at": False,
    }
    assert [(c["name"], c["column_names"]) for c in shape["unique"]] == [
        ("uq_locations_slug", ["slug"])
    ]
    assert [index for index in shape["indexes"] if not index.get("duplicates_constraint")] == []


async def test_migrated_dining_tables_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("dining_tables"),
            "foreign_keys": inspector.get_foreign_keys("dining_tables"),
            "unique": inspector.get_unique_constraints("dining_tables"),
            "indexes": inspector.get_indexes("dining_tables"),
            "checks": inspector.get_check_constraints("dining_tables"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "location_id": False,
        "label": False,
        "capacity": False,
    }
    [foreign_key] = shape["foreign_keys"]
    assert foreign_key["name"] == "fk_dining_tables_location_id_locations"
    assert foreign_key["constrained_columns"] == ["location_id"]
    assert foreign_key["referred_table"] == "locations"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert [(c["name"], c["column_names"]) for c in shape["unique"]] == [
        ("uq_dining_tables_location_id_label", ["location_id", "label"])
    ]
    assert [index for index in shape["indexes"] if not index.get("duplicates_constraint")] == []
    assert [check["name"] for check in shape["checks"]] == [
        "ck_dining_tables_capacity_between_2_and_8"
    ]


@pytest.mark.parametrize("capacity", [1, 9])
async def test_dining_table_capacity_must_be_between_2_and_8(
    session_factory: async_sessionmaker[AsyncSession], capacity: int
) -> None:
    async with session_factory() as session:
        location = Location(
            slug="test-square",
            address="Test Square",
            description="About test-square",
            image_key="locations/test-square.jpg",
        )
        session.add(location)
        await session.flush()
        session.add(DiningTable(location_id=location.id, label="Table 1", capacity=capacity))

        with pytest.raises(IntegrityError, match="ck_dining_tables_capacity_between_2_and_8"):
            await session.flush()
