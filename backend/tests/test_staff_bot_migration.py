import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection
from support.bookings import WAITER_BOT
from support.migrations import BOT_PASSWORD_HASH, run_revision

from app.model_registry import User

pytestmark = pytest.mark.anyio

STAFF_BOT = "0018_add_staff_bot.py"


async def count_bots(connection: AsyncConnection) -> int:
    count = await connection.scalar(
        select(func.count()).select_from(User).where(User.email == WAITER_BOT)
    )
    assert count is not None
    return count


async def test_migrations_add_the_staff_bot_locally(connection: AsyncConnection) -> None:
    rows = (
        await connection.execute(
            select(
                User.first_name,
                User.last_name,
                User.is_staff,
                User.email_verified_at.is_not(None),
                User.password_hash,
            ).where(User.email == WAITER_BOT)
        )
    ).all()

    assert [tuple(row) for row in rows] == [("Waiter", "Bot", True, True, BOT_PASSWORD_HASH)]


# The outer test transaction is rolled back afterwards, so later tests still see the bot.
@pytest.mark.parametrize("environment", ["staging", "prod"])
async def test_the_staff_bot_is_never_added_on_staging_or_prod(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await connection.execute(delete(User).where(User.email == WAITER_BOT))

    await run_revision(
        connection, monkeypatch, file_name=STAFF_BOT, step="upgrade", environment=environment
    )

    assert await count_bots(connection) == 0


async def test_the_downgrade_removes_the_staff_bot_locally(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_revision(
        connection, monkeypatch, file_name=STAFF_BOT, step="downgrade", environment="local"
    )

    assert await count_bots(connection) == 0
