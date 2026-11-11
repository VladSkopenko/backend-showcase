import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.model_registry import Booking, BookingParticipant, DiningTable, Location, User

SEARCH = "/api/v1/bookings/tables"
BOOKINGS = "/api/v1/bookings"
LOGIN = "/api/v1/auth/login"
MEDIA_BASE_URL = "https://media.example.com/n/ns/b/media/o"
PASSWORD = "correct-horse"
ADA = "ada@example.com"
GRACE = "grace@example.com"
TZ = ZoneInfo("Asia/Tbilisi")
TODAY = date(2026, 11, 12)
TOMORROW = TODAY + timedelta(days=1)
DURATION = timedelta(minutes=90)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


START = at(TODAY, 13, 10).astimezone(UTC)


def grid(day: date) -> list[datetime]:
    return [at(day, 10) + timedelta(minutes=30 * step) for step in range(24)]


@dataclass
class FakeClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@dataclass
class Venue:
    first: Location
    second: Location
    four: DiningTable
    small: DiningTable
    six: DiningTable
    other: DiningTable
    eight: DiningTable


async def sign_in(client: httpx2.AsyncClient, email: str) -> None:
    client.cookies.clear()
    response = await client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


async def add_booking(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    table: DiningTable,
    starts_at: datetime,
    status: BookingStatus = BookingStatus.CONFIRMED,
    duration: timedelta = DURATION,
    party_size: int = 2,
) -> Booking:
    booking = Booking(
        user_id=user.id,
        table_id=table.id,
        party_size=party_size,
        starts_at=starts_at,
        ends_at=starts_at + duration,
        status=status,
    )
    async with session_factory() as session:
        session.add(booking)
        await session.flush()
        session.add(
            BookingParticipant(
                booking_id=booking.id,
                user_id=user.id,
                role=ParticipantRole.OWNER,
                created_at=clock.now(),
            )
        )
        await session.commit()
    return booking


def as_guest(token: str) -> dict[str, str]:
    return {"Cookie": f"guest_token={token}"}


async def book(
    client: httpx2.AsyncClient, table_id: uuid.UUID, starts_at: datetime | str, party_size: int = 2
) -> httpx2.Response:
    start = starts_at if isinstance(starts_at, str) else starts_at.isoformat()
    return await client.post(
        BOOKINGS, json={"table_id": str(table_id), "starts_at": start, "party_size": party_size}
    )


async def cancel(client: httpx2.AsyncClient, booking_id: str | uuid.UUID) -> httpx2.Response:
    return await client.post(f"{BOOKINGS}/{booking_id}/cancel")


async def edit(
    client: httpx2.AsyncClient,
    booking_id: str | uuid.UUID,
    starts_at: datetime | str,
    party_size: int = 2,
    duration_minutes: int = 90,
) -> httpx2.Response:
    start = starts_at if isinstance(starts_at, str) else starts_at.isoformat()
    return await client.put(
        f"{BOOKINGS}/{booking_id}",
        json={"starts_at": start, "party_size": party_size, "duration_minutes": duration_minutes},
    )


def assert_error(response: httpx2.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["code"] == code


def location_body(location: Location) -> dict[str, str]:
    return {
        "id": str(location.id),
        "address": location.address,
        "image_url": f"{MEDIA_BASE_URL}/{location.image_key}",
    }


async def stored_participants(
    connection: AsyncConnection, booking_id: str | uuid.UUID
) -> list[tuple[uuid.UUID | None, uuid.UUID | None, ParticipantRole]]:
    rows = await connection.execute(
        select(BookingParticipant.user_id, BookingParticipant.guest_id, BookingParticipant.role)
        .where(BookingParticipant.booking_id == uuid.UUID(str(booking_id)))
        .order_by(BookingParticipant.created_at, BookingParticipant.role)
    )
    return [(row[0], row[1], row[2]) for row in rows]
