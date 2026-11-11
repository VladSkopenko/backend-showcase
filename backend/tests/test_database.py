from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common.database import get_session
from app.features.core.auth.enums import OAuthProvider
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.model_registry import (
    Booking,
    BookingInvite,
    BookingParticipant,
    DiningTable,
    Guest,
    Location,
    OAuthAccount,
    User,
)

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


async def test_migrated_bookings_table_has_the_expected_shape(connection: AsyncConnection) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("bookings"),
            "foreign_keys": inspector.get_foreign_keys("bookings"),
            "indexes": inspector.get_indexes("bookings"),
            "checks": inspector.get_check_constraints("bookings"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "user_id": False,
        "table_id": False,
        "party_size": False,
        "starts_at": False,
        "ends_at": False,
        "status": False,
        "created_at": False,
        "updated_at": False,
    }
    assert sorted(
        (fk["name"], fk["constrained_columns"], fk["referred_table"], fk["options"]["ondelete"])
        for fk in shape["foreign_keys"]
    ) == [
        ("fk_bookings_table_id_dining_tables", ["table_id"], "dining_tables", "CASCADE"),
        ("fk_bookings_user_id_users", ["user_id"], "users", "CASCADE"),
    ]
    indexes = [index for index in shape["indexes"] if not index.get("duplicates_constraint")]
    assert [(index["name"], index["column_names"]) for index in indexes] == [
        ("ix_bookings_user_id", ["user_id"])
    ]
    assert sorted((check["name"], check["sqltext"]) for check in shape["checks"]) == [
        ("ck_bookings_ends_at_after_starts_at", "ends_at > starts_at"),
        ("ck_bookings_party_size_between_1_and_8", "party_size >= 1 AND party_size <= 8"),
    ]


async def test_booking_status_enum_has_both_labels(connection: AsyncConnection) -> None:
    labels = await connection.scalar(text("SELECT enum_range(NULL::booking_status)::text[]"))

    assert labels == ["CONFIRMED", "CANCELLED"]


async def test_bookings_status_defaults_to_confirmed(connection: AsyncConnection) -> None:
    default = await connection.scalar(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'bookings' AND column_name = 'status'"
        )
    )

    assert default == "'CONFIRMED'::booking_status"


async def test_bookings_exclusion_constraint_covers_confirmed_rows_per_table(
    connection: AsyncConnection,
) -> None:
    # alembic check cannot reflect exclusion constraints, so this pins the definition.
    definition = await connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ex_bookings_table_id_period'"
        )
    )

    assert definition == (
        "EXCLUDE USING gist (table_id WITH =, tstzrange(starts_at, ends_at) WITH &&) "
        "WHERE ((status = 'CONFIRMED'::booking_status))"
    )


BOOKING_START = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)


async def add_table_and_user(session: AsyncSession) -> tuple[DiningTable, User]:
    location = Location(
        slug="test-square",
        address="Test Square",
        description="About test-square",
        image_key="locations/test-square.jpg",
    )
    user = User(first_name="Ada", last_name="Lovelace", email="ada@example.com")
    session.add_all([location, user])
    await session.flush()
    table = DiningTable(location_id=location.id, label="Table 1", capacity=4)
    session.add(table)
    await session.flush()
    return table, user


def booking(
    table: DiningTable, user: User, *, minutes: int, status: BookingStatus = BookingStatus.CONFIRMED
) -> Booking:
    starts_at = BOOKING_START + timedelta(minutes=minutes)
    return Booking(
        user_id=user.id,
        table_id=table.id,
        party_size=2,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=90),
        status=status,
    )


async def test_cancelled_overlaps_and_adjacent_bookings_fit_the_exclusion_constraint(
    session_factory: async_sessionmaker[AsyncSession], connection: AsyncConnection
) -> None:
    async with session_factory() as session:
        table, user = await add_table_and_user(session)
        session.add(booking(table, user, minutes=0))
        await session.flush()
        session.add(booking(table, user, minutes=30, status=BookingStatus.CANCELLED))
        await session.flush()
        session.add(booking(table, user, minutes=90))
        await session.flush()
        session.add(booking(table, user, minutes=-90))
        await session.commit()

    assert await connection.scalar(select(func.count()).select_from(Booking)) == 4


async def test_overlapping_confirmed_bookings_on_one_table_fail_the_exclusion_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        table, user = await add_table_and_user(session)
        session.add(booking(table, user, minutes=0))
        await session.flush()
        session.add(booking(table, user, minutes=60))

        with pytest.raises(IntegrityError, match="ex_bookings_table_id_period"):
            await session.flush()


@pytest.mark.parametrize(
    ("party_size", "minutes", "constraint"),
    [
        (0, 90, "ck_bookings_party_size_between_1_and_8"),
        (9, 90, "ck_bookings_party_size_between_1_and_8"),
        (2, 0, "ck_bookings_ends_at_after_starts_at"),
    ],
)
async def test_booking_checks(
    session_factory: async_sessionmaker[AsyncSession],
    party_size: int,
    minutes: int,
    constraint: str,
) -> None:
    async with session_factory() as session:
        table, user = await add_table_and_user(session)
        session.add(
            Booking(
                user_id=user.id,
                table_id=table.id,
                party_size=party_size,
                starts_at=BOOKING_START,
                ends_at=BOOKING_START + timedelta(minutes=minutes),
            )
        )

        with pytest.raises(IntegrityError, match=constraint):
            await session.flush()


async def test_migrated_guests_table_has_the_expected_shape(connection: AsyncConnection) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("guests"),
            "unique": inspector.get_unique_constraints("guests"),
            "indexes": inspector.get_indexes("guests"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "name": False,
        "token_hash": False,
        "expires_at": False,
        "created_at": False,
        "updated_at": False,
    }
    assert [(c["name"], c["column_names"]) for c in shape["unique"]] == [
        ("uq_guests_token_hash", ["token_hash"])
    ]
    assert [index for index in shape["indexes"] if not index.get("duplicates_constraint")] == []


async def test_migrated_booking_participants_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("booking_participants"),
            "foreign_keys": inspector.get_foreign_keys("booking_participants"),
            "unique": inspector.get_unique_constraints("booking_participants"),
            "indexes": inspector.get_indexes("booking_participants"),
            "checks": inspector.get_check_constraints("booking_participants"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "id": False,
        "booking_id": False,
        "user_id": True,
        "guest_id": True,
        "role": False,
        "created_at": False,
    }
    assert sorted(
        (fk["name"], fk["constrained_columns"], fk["referred_table"], fk["options"]["ondelete"])
        for fk in shape["foreign_keys"]
    ) == [
        ("fk_booking_participants_booking_id_bookings", ["booking_id"], "bookings", "CASCADE"),
        ("fk_booking_participants_guest_id_guests", ["guest_id"], "guests", "CASCADE"),
        ("fk_booking_participants_user_id_users", ["user_id"], "users", "CASCADE"),
    ]
    assert sorted((c["name"], c["column_names"]) for c in shape["unique"]) == [
        ("uq_booking_participants_booking_id_guest_id", ["booking_id", "guest_id"]),
        ("uq_booking_participants_booking_id_user_id", ["booking_id", "user_id"]),
    ]
    indexes = [index for index in shape["indexes"] if not index.get("duplicates_constraint")]
    assert sorted((index["name"], index["column_names"], index["unique"]) for index in indexes) == [
        ("ix_booking_participants_booking_id_owner", ["booking_id"], True),
        ("ix_booking_participants_guest_id", ["guest_id"], False),
        ("ix_booking_participants_user_id", ["user_id"], False),
    ]
    [owner_index] = [
        index for index in indexes if index["name"] == "ix_booking_participants_booking_id_owner"
    ]
    assert owner_index["dialect_options"]["postgresql_where"] == (
        "(role = 'OWNER'::participant_role)"
    )
    assert [(check["name"], check["sqltext"]) for check in shape["checks"]] == [
        ("ck_booking_participants_one_of_user_id_guest_id", "num_nonnulls(user_id, guest_id) = 1")
    ]


async def test_participant_role_enum_has_both_labels(connection: AsyncConnection) -> None:
    labels = await connection.scalar(text("SELECT enum_range(NULL::participant_role)::text[]"))

    assert labels == ["OWNER", "GUEST"]


async def test_migrated_booking_invites_table_has_the_expected_shape(
    connection: AsyncConnection,
) -> None:
    def describe(sync_connection: Connection) -> dict[str, Any]:
        inspector = inspect(sync_connection)
        return {
            "columns": inspector.get_columns("booking_invites"),
            "primary_key": inspector.get_pk_constraint("booking_invites"),
            "foreign_keys": inspector.get_foreign_keys("booking_invites"),
            "unique": inspector.get_unique_constraints("booking_invites"),
            "indexes": inspector.get_indexes("booking_invites"),
        }

    shape = await connection.run_sync(describe)

    assert {column["name"]: column["nullable"] for column in shape["columns"]} == {
        "booking_id": False,
        "code": False,
        "created_at": False,
    }
    assert shape["primary_key"]["name"] == "pk_booking_invites"
    assert shape["primary_key"]["constrained_columns"] == ["booking_id"]
    [foreign_key] = shape["foreign_keys"]
    assert foreign_key["name"] == "fk_booking_invites_booking_id_bookings"
    assert foreign_key["referred_table"] == "bookings"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert [(c["name"], c["column_names"]) for c in shape["unique"]] == [
        ("uq_booking_invites_code", ["code"])
    ]
    assert [index for index in shape["indexes"] if not index.get("duplicates_constraint")] == []


async def add_booking_with_owner(session: AsyncSession) -> tuple[Booking, User]:
    table, user = await add_table_and_user(session)
    owned = booking(table, user, minutes=0)
    session.add(owned)
    await session.flush()
    session.add(
        BookingParticipant(
            booking_id=owned.id,
            user_id=user.id,
            role=ParticipantRole.OWNER,
            created_at=BOOKING_START,
        )
    )
    await session.flush()
    return owned, user


async def add_guest(session: AsyncSession) -> Guest:
    guest = Guest(name="Alex", token_hash="a" * 64, expires_at=BOOKING_START + timedelta(days=31))
    session.add(guest)
    await session.flush()
    return guest


@pytest.mark.parametrize("identity", ["none", "both"])
async def test_a_participant_is_exactly_one_of_a_user_and_a_guest(
    session_factory: async_sessionmaker[AsyncSession], identity: str
) -> None:
    async with session_factory() as session:
        owned, user = await add_booking_with_owner(session)
        guest = await add_guest(session)
        session.add(
            BookingParticipant(
                booking_id=owned.id,
                user_id=None if identity == "none" else user.id,
                guest_id=None if identity == "none" else guest.id,
                role=ParticipantRole.GUEST,
                created_at=BOOKING_START,
            )
        )

        with pytest.raises(IntegrityError, match="ck_booking_participants_one_of_user_id_guest_id"):
            await session.flush()


async def test_a_user_joins_a_booking_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        owned, user = await add_booking_with_owner(session)
        session.add(
            BookingParticipant(
                booking_id=owned.id,
                user_id=user.id,
                role=ParticipantRole.GUEST,
                created_at=BOOKING_START,
            )
        )

        with pytest.raises(IntegrityError, match="uq_booking_participants_booking_id_user_id"):
            await session.flush()


async def test_a_guest_joins_a_booking_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        owned, _ = await add_booking_with_owner(session)
        guest = await add_guest(session)
        session.add_all(
            [
                BookingParticipant(
                    booking_id=owned.id,
                    guest_id=guest.id,
                    role=ParticipantRole.GUEST,
                    created_at=BOOKING_START,
                )
                for _ in range(2)
            ]
        )

        with pytest.raises(IntegrityError, match="uq_booking_participants_booking_id_guest_id"):
            await session.flush()


async def test_a_booking_has_one_owner(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        owned, _ = await add_booking_with_owner(session)
        guest = await add_guest(session)
        session.add(
            BookingParticipant(
                booking_id=owned.id,
                guest_id=guest.id,
                role=ParticipantRole.OWNER,
                created_at=BOOKING_START,
            )
        )

        with pytest.raises(IntegrityError, match="ix_booking_participants_booking_id_owner"):
            await session.flush()


async def test_guest_token_hashes_are_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await add_guest(session)
        session.add(Guest(name="Bea", token_hash="a" * 64, expires_at=BOOKING_START))

        with pytest.raises(IntegrityError, match="uq_guests_token_hash"):
            await session.flush()


async def test_invite_codes_are_unique(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        first, user = await add_booking_with_owner(session)
        second = Booking(
            user_id=user.id,
            table_id=first.table_id,
            party_size=2,
            starts_at=first.ends_at,
            ends_at=first.ends_at + timedelta(minutes=90),
        )
        session.add(second)
        await session.flush()
        session.add(BookingInvite(booking_id=first.id, code="same-code", created_at=BOOKING_START))
        await session.flush()
        session.add(BookingInvite(booking_id=second.id, code="same-code", created_at=BOOKING_START))

        with pytest.raises(IntegrityError, match="uq_booking_invites_code"):
            await session.flush()
