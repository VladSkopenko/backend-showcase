import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from support.migrations import BOT_PASSWORD_HASH, load_revision, run_revision

from app.model_registry import User

pytestmark = pytest.mark.anyio

BOOKING_BOTS = "0011_add_dev_booking_bots.py"
GUEST_BOTS = "0020_add_dev_guest_bots.py"
FIRST_BOTS = [f"booking-bot-{number}@example.com" for number in range(1, 5)]
GUEST_BOT_EMAILS = [f"booking-bot-{number}@example.com" for number in range(5, 41)]


async def bot_emails(connection: AsyncConnection) -> set[str]:
    rows = await connection.scalars(select(User.email).where(User.email.like("booking-bot-%")))
    return set(rows)


# The outer test transaction is rolled back afterwards, so later tests see no bots.
async def test_the_dev_upgrade_adds_named_verified_guest_bots(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_revision(
        connection, monkeypatch, file_name=GUEST_BOTS, step="upgrade", environment="dev"
    )

    rows = (
        await connection.execute(
            select(
                User.email,
                User.first_name,
                User.last_name,
                User.email_verified_at,
                User.created_at,
                User.updated_at,
                User.password_hash,
                User.is_staff,
            ).where(User.email.in_(GUEST_BOT_EMAILS))
        )
    ).all()

    created = load_revision(GUEST_BOTS).CREATED
    assert sorted(row.email for row in rows) == sorted(GUEST_BOT_EMAILS)
    assert len({(row.first_name, row.last_name) for row in rows}) == len(GUEST_BOT_EMAILS)
    assert all(row.first_name != "Booking" for row in rows)
    assert {
        (row.email_verified_at, row.created_at, row.updated_at, row.password_hash, row.is_staff)
        for row in rows
    } == {(created, created, created, BOT_PASSWORD_HASH, False)}


@pytest.mark.parametrize("environment", ["local", "staging", "prod"])
async def test_the_guest_bots_are_never_added_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection, monkeypatch, file_name=GUEST_BOTS, step="upgrade", environment=environment
    )

    assert await bot_emails(connection) == set()


async def test_the_dev_downgrade_removes_only_the_guest_bots(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    for file_name in (BOOKING_BOTS, GUEST_BOTS):
        await run_revision(
            connection, monkeypatch, file_name=file_name, step="upgrade", environment="dev"
        )

    await run_revision(
        connection, monkeypatch, file_name=GUEST_BOTS, step="downgrade", environment="dev"
    )

    assert await bot_emails(connection) == set(FIRST_BOTS)


@pytest.mark.parametrize("environment", ["local", "staging", "prod"])
async def test_the_downgrade_keeps_the_guest_bots_outside_dev(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await run_revision(
        connection, monkeypatch, file_name=GUEST_BOTS, step="upgrade", environment="dev"
    )

    await run_revision(
        connection, monkeypatch, file_name=GUEST_BOTS, step="downgrade", environment=environment
    )

    assert await bot_emails(connection) == set(GUEST_BOT_EMAILS)


async def test_the_dev_upgrade_fails_on_a_taken_email(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await connection.execute(
        insert(User).values(first_name="Taken", last_name="Email", email=GUEST_BOT_EMAILS[0])
    )

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await run_revision(
            connection, monkeypatch, file_name=GUEST_BOTS, step="upgrade", environment="dev"
        )
