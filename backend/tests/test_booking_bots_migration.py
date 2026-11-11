import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.anyio


async def test_migrations_add_no_booking_bots_outside_dev(connection: AsyncConnection) -> None:
    count = await connection.scalar(
        text("SELECT count(*) FROM users WHERE email LIKE 'booking-bot-%'")
    )

    assert count == 0
