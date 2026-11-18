import re

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection
from support.migrations import load_revision, run_revision

from app.model_registry import User

pytestmark = pytest.mark.anyio

GRAFANA_READER = "0021_add_grafana_reader_role.py"
ROLE = "grafana_reader"
OTHER_ENVIRONMENTS = ["local", "staging", "prod"]

READABLE_COLUMNS = {
    "bookings": {
        "id",
        "user_id",
        "table_id",
        "party_size",
        "starts_at",
        "ends_at",
        "status",
        "decided_at",
        "decided_by_id",
        "created_at",
        "updated_at",
    },
    "booking_participants": {"id", "booking_id", "user_id", "guest_id", "role", "created_at"},
    "dining_tables": {"id", "location_id", "label", "capacity"},
    "locations": {
        "id",
        "slug",
        "address",
        "description",
        "image_key",
        "created_at",
        "updated_at",
    },
    "dishes": {
        "id",
        "slug",
        "name",
        "description",
        "category",
        "price_cents",
        "weight_grams",
        "calories",
        "protein",
        "fats",
        "carbs",
        "vitamins",
        "is_available",
        "popularity",
        "prep_minutes",
        "image_key",
        "created_at",
        "updated_at",
    },
    "preorder_items": {
        "id",
        "participant_id",
        "dish_id",
        "quantity",
        "state",
        "submission_id",
        "submitted_at",
        "created_at",
        "updated_at",
    },
    "users": {"id", "first_name", "last_name"},
}

DENIED = [
    "SELECT email FROM users",
    "SELECT password_hash FROM users",
    "SELECT * FROM users",
    "SELECT note FROM preorder_items",
    "SELECT * FROM preorder_items",
    "SELECT count(*) FROM guests",
    "SELECT count(*) FROM booking_invites",
    "SELECT count(*) FROM refresh_tokens",
    "SELECT count(*) FROM verification_codes",
    "SELECT count(*) FROM user_oauth_accounts",
    "SELECT count(*) FROM alembic_version",
    "INSERT INTO dishes (slug) VALUES ('grafana-reader-write')",
    "UPDATE users SET first_name = 'x'",
    "DELETE FROM bookings",
    "CREATE TABLE grafana_reader_scratch (x integer)",
    "CREATE SCHEMA grafana_reader_scratch",
    "CREATE TEMPORARY TABLE grafana_reader_scratch (x integer)",
    "SELECT lo_creat(-1)",
    "SELECT lo_create(0)",
    "SELECT lo_from_bytea(0, 'x')",
]


async def upgrade(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection, monkeypatch, file_name=GRAFANA_READER, step="upgrade", environment=environment
    )


async def downgrade(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection,
        monkeypatch,
        file_name=GRAFANA_READER,
        step="downgrade",
        environment=environment,
    )


async def role_exists(connection: AsyncConnection) -> bool:
    count = await connection.scalar(
        text("SELECT count(*) FROM pg_roles WHERE rolname = :role"), {"role": ROLE}
    )
    return bool(count)


async def granted_columns(connection: AsyncConnection) -> dict[str, set[str]]:
    rows = await connection.execute(
        text(
            "SELECT table_name, column_name, privilege_type "
            "FROM information_schema.column_privileges WHERE grantee = :role"
        ),
        {"role": ROLE},
    )
    granted: dict[str, set[str]] = {}
    for table_name, column_name, privilege_type in rows:
        assert privilege_type == "SELECT"
        granted.setdefault(table_name, set()).add(column_name)
    return granted


async def public_may_write_to_disk(connection: AsyncConnection) -> set[bool]:
    row = (
        await connection.execute(
            text(
                "SELECT has_database_privilege('public', current_database(), 'TEMPORARY'), "
                "has_function_privilege('public', 'lo_creat(integer)', 'EXECUTE'), "
                "has_function_privilege('public', 'lo_create(oid)', 'EXECUTE'), "
                "has_function_privilege('public', 'lo_from_bytea(oid, bytea)', 'EXECUTE')"
            )
        )
    ).one()
    return set(row)


# The outer test transaction is rolled back afterwards, so the role never outlives a test.
async def test_the_dev_upgrade_creates_a_limited_login_role(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    row = (
        await connection.execute(
            text(
                "SELECT rolcanlogin, rolconnlimit, rolsuper, rolcreaterole, rolcreatedb, "
                "rolreplication, rolbypassrls, rolpassword, setconfig "
                "FROM pg_authid JOIN pg_db_role_setting "
                "ON setrole = pg_authid.oid AND setdatabase = 0 WHERE rolname = :role"
            ),
            {"role": ROLE},
        )
    ).one()

    verifier = load_revision(GRAFANA_READER).VERIFIER
    assert re.fullmatch(
        r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+", verifier
    )
    assert row.rolcanlogin is True
    assert row.rolconnlimit == 5
    assert (
        row.rolsuper,
        row.rolcreaterole,
        row.rolcreatedb,
        row.rolreplication,
        row.rolbypassrls,
    ) == (False, False, False, False, False)
    assert set(row.setconfig) == {
        "statement_timeout=5s",
        "default_transaction_read_only=on",
        "temp_file_limit=64MB",
    }
    assert row.rolpassword == verifier


async def test_the_dev_upgrade_grants_exactly_the_listed_columns(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    table_grants = await connection.scalar(
        text("SELECT count(*) FROM information_schema.table_privileges WHERE grantee = :role"),
        {"role": ROLE},
    )

    assert await granted_columns(connection) == READABLE_COLUMNS
    assert table_grants == 0


async def test_the_role_reads_names_and_restaurant_data(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await connection.execute(
        insert(User).values(first_name="Nino", last_name="Reader", email="nino@example.com")
    )
    await upgrade(connection, monkeypatch, "dev")
    await connection.execute(text(f"SET LOCAL ROLE {ROLE}"))

    names = (
        await connection.execute(
            text("SELECT first_name, last_name FROM users WHERE first_name = 'Nino'")
        )
    ).all()
    for table_name, columns in READABLE_COLUMNS.items():
        column_list = ", ".join(f'"{column}"' for column in sorted(columns))
        await connection.execute(text(f"SELECT {column_list} FROM {table_name}"))

    assert names == [("Nino", "Reader")]


@pytest.mark.parametrize("statement", DENIED)
async def test_the_role_is_denied_personal_data_and_writes(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    await upgrade(connection, monkeypatch, "dev")
    await connection.execute(text(f"SET LOCAL ROLE {ROLE}"))

    with pytest.raises(ProgrammingError, match="permission denied"):
        await connection.execute(text(statement))


async def test_the_dev_upgrade_closes_disk_writes_for_public(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await public_may_write_to_disk(connection) == {True}

    await upgrade(connection, monkeypatch, "dev")

    assert await public_may_write_to_disk(connection) == {False}


@pytest.mark.parametrize("environment", OTHER_ENVIRONMENTS)
async def test_the_role_is_never_created_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await upgrade(connection, monkeypatch, environment)

    assert not await role_exists(connection)
    assert await public_may_write_to_disk(connection) == {True}


async def test_the_dev_downgrade_removes_the_role_and_restores_public(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    await downgrade(connection, monkeypatch, "dev")

    assert not await role_exists(connection)
    assert await granted_columns(connection) == {}
    assert await public_may_write_to_disk(connection) == {True}


@pytest.mark.parametrize("environment", OTHER_ENVIRONMENTS)
async def test_the_downgrade_keeps_the_role_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    await downgrade(connection, monkeypatch, environment)

    assert await role_exists(connection)
    assert await public_may_write_to_disk(connection) == {False}


async def test_the_dev_upgrade_fails_on_a_taken_role_name(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await connection.execute(text(f"CREATE ROLE {ROLE}"))

    with pytest.raises(ProgrammingError, match="already exists"):
        await upgrade(connection, monkeypatch, "dev")
