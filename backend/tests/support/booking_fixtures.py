from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.model_registry import DiningTable, Location, User
from support.bookings import ADA, GRACE, PASSWORD, START, FakeClock, Venue


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", fake.now)
    return fake


@pytest.fixture
async def no_locations(connection: AsyncConnection) -> None:
    await connection.execute(text("DELETE FROM locations"))


@pytest.fixture
async def venue(session_factory: async_sessionmaker[AsyncSession]) -> Venue:
    first = Location(
        slug="old-town-square",
        address="Old Town Square",
        description="About old-town-square",
        image_key="locations/old-town-square.jpg",
        created_at=START,
    )
    second = Location(
        slug="river-embankment",
        address="River Embankment",
        description="About river-embankment",
        image_key="locations/river-embankment.jpg",
        created_at=START + timedelta(minutes=1),
    )
    async with session_factory() as session:
        session.add_all([second, first])
        await session.flush()
        venue = Venue(
            first=first,
            second=second,
            small=DiningTable(location_id=first.id, label="Table 10", capacity=2),
            four=DiningTable(location_id=first.id, label="Table 2", capacity=4),
            six=DiningTable(location_id=first.id, label="Table 3", capacity=6),
            other=DiningTable(location_id=second.id, label="Table 1", capacity=4),
            eight=DiningTable(location_id=second.id, label="Table 2", capacity=8),
        )
        session.add_all([venue.small, venue.four, venue.six, venue.other, venue.eight])
        await session.commit()
    return venue


@pytest.fixture
async def users(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, User]:
    password_hash = await PasswordHasher().hash(password=PASSWORD)
    created = {
        email: User(
            first_name=email.split("@")[0].title(),
            last_name="Tester",
            email=email,
            password_hash=password_hash,
            email_verified_at=START - timedelta(days=1),
        )
        for email in (ADA, GRACE)
    }
    async with session_factory() as session:
        session.add_all(created.values())
        await session.commit()
    return created
