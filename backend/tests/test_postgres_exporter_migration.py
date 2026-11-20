import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection
from support.migrations import load_revision, run_revision

pytestmark = pytest.mark.anyio

POSTGRES_EXPORTER = "0026_add_postgres_exporter_role.py"
ROLE = "postgres_exporter"
OTHER_ENVIRONMENTS = ["local", "staging", "prod"]


async def upgrade(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection,
        monkeypatch,
        file_name=POSTGRES_EXPORTER,
        step="upgrade",
        environment=environment,
    )


async def downgrade(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection,
        monkeypatch,
        file_name=POSTGRES_EXPORTER,
        step="downgrade",
        environment=environment,
    )


async def role_exists(connection: AsyncConnection) -> bool:
    count = await connection.scalar(
        text("SELECT count(*) FROM pg_roles WHERE rolname = :role"), {"role": ROLE}
    )
    return bool(count)


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

    verifier = load_revision(POSTGRES_EXPORTER).VERIFIER
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
    assert set(row.setconfig) == {"statement_timeout=5s", "default_transaction_read_only=on"}
    assert row.rolpassword == verifier


async def test_the_role_has_no_memberships_and_no_grants(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    memberships = await connection.scalar(
        text(
            "SELECT count(*) FROM pg_auth_members "
            "JOIN pg_roles ON pg_roles.oid = pg_auth_members.member WHERE rolname = :role"
        ),
        {"role": ROLE},
    )
    table_grants = await connection.scalar(
        text("SELECT count(*) FROM information_schema.table_privileges WHERE grantee = :role"),
        {"role": ROLE},
    )
    column_grants = await connection.scalar(
        text("SELECT count(*) FROM information_schema.column_privileges WHERE grantee = :role"),
        {"role": ROLE},
    )

    assert (memberships, table_grants, column_grants) == (0, 0, 0)


@pytest.mark.parametrize("environment", OTHER_ENVIRONMENTS)
async def test_the_role_is_never_created_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await upgrade(connection, monkeypatch, environment)

    assert not await role_exists(connection)


async def test_the_dev_downgrade_removes_the_role(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    await downgrade(connection, monkeypatch, "dev")

    assert not await role_exists(connection)


@pytest.mark.parametrize("environment", OTHER_ENVIRONMENTS)
async def test_the_downgrade_keeps_the_role_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await upgrade(connection, monkeypatch, "dev")

    await downgrade(connection, monkeypatch, environment)

    assert await role_exists(connection)


async def test_the_dev_upgrade_fails_on_a_taken_role_name(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await connection.execute(text(f"CREATE ROLE {ROLE}"))

    with pytest.raises(ProgrammingError, match="already exists"):
        await upgrade(connection, monkeypatch, "dev")
