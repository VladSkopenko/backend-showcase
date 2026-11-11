import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.config.settings import Settings, get_settings
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.bookings.enums import BookingStatus
from app.main import create_app
from app.model_registry import Booking, DiningTable, Location, User

pytestmark = pytest.mark.anyio

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


# 13:10 in Tbilisi (+04:00).
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


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", fake.now)
    return fake


@pytest.fixture(autouse=True)
async def no_locations(connection: AsyncConnection) -> None:
    await connection.execute(text("DELETE FROM locations"))


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


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
) -> Booking:
    booking = Booking(
        user_id=user.id,
        table_id=table.id,
        party_size=2,
        starts_at=starts_at,
        ends_at=starts_at + DURATION,
        status=status,
    )
    async with session_factory() as session:
        session.add(booking)
        await session.commit()
    return booking


async def search(client: httpx2.AsyncClient, **params: Any) -> httpx2.Response:
    return await client.get(SEARCH, params={"date": str(TOMORROW), "party_size": 2, **params})


async def book(
    client: httpx2.AsyncClient, table_id: uuid.UUID, starts_at: datetime | str, party_size: int = 2
) -> httpx2.Response:
    start = starts_at if isinstance(starts_at, str) else starts_at.isoformat()
    return await client.post(
        BOOKINGS, json={"table_id": str(table_id), "starts_at": start, "party_size": party_size}
    )


async def cancel(client: httpx2.AsyncClient, booking_id: str | uuid.UUID) -> httpx2.Response:
    return await client.post(f"{BOOKINGS}/{booking_id}/cancel")


def card_ids(response: httpx2.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [card["id"] for card in response.json()["items"]]


def availability(response: httpx2.Response, table: DiningTable) -> dict[datetime, bool]:
    [card] = [card for card in response.json()["items"] if card["id"] == str(table.id)]
    return {datetime.fromisoformat(slot["starts_at"]): slot["available"] for slot in card["slots"]}


def assert_error(response: httpx2.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["code"] == code


def location_body(location: Location) -> dict[str, str]:
    return {
        "id": str(location.id),
        "address": location.address,
        "image_url": f"{MEDIA_BASE_URL}/{location.image_key}",
    }


async def count_bookings(connection: AsyncConnection) -> int:
    count = await connection.scalar(select(func.count()).select_from(Booking))
    assert count is not None
    return count


async def stored_status(connection: AsyncConnection, booking_id: str | uuid.UUID) -> BookingStatus:
    status: BookingStatus | None = await connection.scalar(
        select(Booking.status).where(Booking.id == uuid.UUID(str(booking_id)))
    )
    assert status is not None
    return status


async def test_search_lists_fitting_tables_of_every_location_with_the_full_day_grid(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    response = await search(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert card_ids(response) == [str(venue.four.id), str(venue.small.id), str(venue.other.id)]
    assert body["items"][0] == {
        "id": str(venue.four.id),
        "label": "Table 2",
        "capacity": 4,
        "location": location_body(venue.first),
        "slots": [{"starts_at": start.isoformat(), "available": True} for start in grid(TOMORROW)],
    }
    assert body["items"][2]["location"] == location_body(venue.second)


@pytest.mark.parametrize(
    ("party_size", "tables"), [(1, ["four", "small", "other"]), (3, ["four", "other"])]
)
async def test_search_lists_tables_from_the_party_size_up(
    client: httpx2.AsyncClient, venue: Venue, party_size: int, tables: list[str]
) -> None:
    response = await search(client, party_size=party_size)

    assert card_ids(response) == [str(getattr(venue, table).id) for table in tables]


async def test_search_skips_a_table_with_no_available_slot(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for start in grid(TOMORROW)[::3]:
        await add_booking(session_factory, user=users[GRACE], table=venue.small, starts_at=start)

    response = await search(client)

    assert card_ids(response) == [str(venue.four.id), str(venue.other.id)]
    assert response.json()["total"] == 2


async def test_search_at_a_time_keeps_only_tables_free_then_each_with_the_full_grid(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 12)
    )

    response = await search(client, time="12:00")

    assert card_ids(response) == [str(venue.small.id), str(venue.other.id)]
    assert all(len(card["slots"]) == 24 for card in response.json()["items"])


@pytest.mark.parametrize(("days", "status_code"), [(0, 200), (30, 200), (31, 400), (-1, 400)])
async def test_search_dates_run_from_today_to_the_horizon(
    client: httpx2.AsyncClient, venue: Venue, days: int, status_code: int
) -> None:
    response = await search(client, date=str(TODAY + timedelta(days=days)))

    assert response.status_code == status_code, response.text
    if status_code == 400:
        assert response.json()["code"] == "DATE_OUT_OF_RANGE"


@pytest.mark.parametrize(("days", "status_code"), [(0, 200), (30, 200), (31, 400), (-1, 400)])
async def test_search_dates_count_from_the_local_today(
    client: httpx2.AsyncClient,
    venue: Venue,
    fake_clock: FakeClock,
    days: int,
    status_code: int,
) -> None:
    fake_clock.current = at(TODAY, 1).astimezone(UTC)

    response = await search(client, date=str(TODAY + timedelta(days=days)))

    assert response.status_code == status_code, response.text
    if status_code == 400:
        assert response.json()["code"] == "DATE_OUT_OF_RANGE"


async def test_search_sees_a_booking_at_the_last_slot(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 21, 30)
    )

    response = await search(client)

    assert availability(response, venue.four)[at(TOMORROW, 21, 30)] is False


async def test_search_with_every_fitting_table_taken_is_an_empty_page(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for table in (venue.four, venue.small, venue.other):
        await add_booking(
            session_factory, user=users[GRACE], table=table, starts_at=at(TOMORROW, 12)
        )

    response = await search(client, time="12:00")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_search_today_marks_slots_up_to_now_unavailable(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    response = await search(client, date=str(TODAY))

    assert availability(response, venue.four) == {
        start: start > at(TODAY, 13, 10) for start in grid(TODAY)
    }
    assert availability(response, venue.four)[at(TODAY, 13)] is False
    assert availability(response, venue.four)[at(TODAY, 13, 30)] is True


async def test_search_by_location_lists_only_its_tables(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    response = await search(client, location_id=str(venue.second.id))

    assert card_ids(response) == [str(venue.other.id)]


async def test_search_pages_by_limit_and_offset(client: httpx2.AsyncClient, venue: Venue) -> None:
    response = await search(client, limit=1, offset=1)

    assert card_ids(response) == [str(venue.small.id)]
    assert response.json()["total"] == 3
    assert response.json()["limit"] == 1
    assert response.json()["offset"] == 1


@pytest.mark.parametrize(
    ("params", "status_code", "code"),
    [
        ({"party_size": 5}, 400, "PARTY_TOO_LARGE"),
        ({"date": str(TODAY + timedelta(days=31))}, 400, "DATE_OUT_OF_RANGE"),
        ({"date": str(TODAY - timedelta(days=1))}, 400, "DATE_OUT_OF_RANGE"),
        ({"time": "12:15"}, 400, "SLOT_INVALID"),
        ({"time": "12:00:30"}, 400, "SLOT_INVALID"),
        ({"time": "12:00+04:00"}, 400, "SLOT_INVALID"),
        ({"time": "09:30"}, 400, "SLOT_INVALID"),
        ({"time": "22:00"}, 400, "SLOT_INVALID"),
        ({"location_id": str(uuid.uuid4())}, 404, "LOCATION_NOT_FOUND"),
        ({"party_size": 0}, 422, "VALIDATION_ERROR"),
    ],
)
async def test_bad_search_input_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    params: dict[str, Any],
    status_code: int,
    code: str,
) -> None:
    assert_error(await search(client, **params), status_code, code)


@pytest.mark.parametrize(
    ("params", "code"),
    [
        (
            {
                "party_size": 5,
                "date": str(TODAY + timedelta(days=31)),
                "time": "12:15",
                "location_id": str(uuid.uuid4()),
            },
            "PARTY_TOO_LARGE",
        ),
        (
            {
                "date": str(TODAY + timedelta(days=31)),
                "time": "12:15",
                "location_id": str(uuid.uuid4()),
            },
            "DATE_OUT_OF_RANGE",
        ),
        ({"time": "12:15", "location_id": str(uuid.uuid4())}, "SLOT_INVALID"),
    ],
)
async def test_search_reports_the_first_failing_check(
    client: httpx2.AsyncClient, venue: Venue, params: dict[str, Any], code: str
) -> None:
    response = await search(client, **params)

    assert response.json()["code"] == code


async def test_create_confirms_the_booking_and_blocks_the_overlapping_starts(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TOMORROW, 12))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "id": body["id"],
        "status": "CONFIRMED",
        "party_size": 2,
        "starts_at": "2026-11-13T12:00:00+04:00",
        "ends_at": "2026-11-13T13:30:00+04:00",
        "table": {"id": str(venue.four.id), "label": "Table 2", "capacity": 4},
        "location": location_body(venue.first),
    }
    found = await search(client)
    blocked = {at(TOMORROW, 11), at(TOMORROW, 11, 30), at(TOMORROW, 12), at(TOMORROW, 12, 30)}
    blocked.add(at(TOMORROW, 13))
    assert availability(found, venue.four) == {
        start: start not in blocked for start in grid(TOMORROW)
    }
    assert availability(found, venue.four)[at(TOMORROW, 10, 30)] is True
    assert availability(found, venue.four)[at(TOMORROW, 13, 30)] is True
    assert all(availability(found, venue.small).values())


async def test_adjacent_bookings_on_one_table_do_not_overlap(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    assert (await book(client, venue.four.id, at(TOMORROW, 12))).status_code == 201
    await sign_in(client, GRACE)

    after = await book(client, venue.four.id, at(TOMORROW, 13, 30))
    before = await book(client, venue.four.id, at(TOMORROW, 10, 30))

    assert after.status_code == 201, after.text
    assert before.status_code == 201, before.text


@pytest.mark.parametrize("starts_at", ["2026-11-13T08:00:00+00:00", "2026-11-13T08:00:00Z"])
async def test_create_converts_a_start_sent_with_another_offset_to_restaurant_time(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], starts_at: str
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, starts_at)

    assert response.status_code == 201, response.text
    assert response.json()["starts_at"] == "2026-11-13T12:00:00+04:00"
    assert response.json()["ends_at"] == "2026-11-13T13:30:00+04:00"


@pytest.mark.parametrize(
    ("party_size", "starts_at", "code"),
    [
        (5, at(TOMORROW, 12), "PARTY_TOO_LARGE"),
        (2, at(TOMORROW, 12, 15), "SLOT_INVALID"),
        (2, at(TOMORROW, 12) + timedelta(seconds=30), "SLOT_INVALID"),
        (2, at(TOMORROW, 9, 30), "SLOT_INVALID"),
        (2, at(TOMORROW, 22), "SLOT_INVALID"),
        (2, at(TODAY + timedelta(days=31), 12), "DATE_OUT_OF_RANGE"),
        (2, at(TODAY - timedelta(days=1), 12), "DATE_OUT_OF_RANGE"),
    ],
)
async def test_bad_create_input_stores_nothing(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    party_size: int,
    starts_at: datetime,
    code: str,
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, starts_at, party_size=party_size)

    assert_error(response, 400, code)
    assert await count_bookings(connection) == 0


async def test_create_on_the_last_day_of_the_horizon_succeeds(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TODAY + timedelta(days=30), 21, 30))

    assert response.status_code == 201, response.text


async def test_create_with_party_size_zero_is_a_validation_error(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TOMORROW, 12), party_size=0)

    assert_error(response, 422, "VALIDATION_ERROR")


async def test_create_on_a_taken_slot_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TOMORROW, 12, 30))

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert await count_bookings(connection) == 1


@pytest.mark.parametrize(
    ("now", "starts_at", "status_code"),
    [
        (at(TODAY, 13, 10), at(TODAY, 13), 409),
        (at(TODAY, 13), at(TODAY, 13), 409),
        (at(TODAY, 13, 10), at(TODAY, 13, 30), 201),
    ],
)
async def test_create_needs_a_start_later_than_now(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    now: datetime,
    starts_at: datetime,
    status_code: int,
) -> None:
    fake_clock.current = now.astimezone(UTC)
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, starts_at)

    assert response.status_code == status_code, response.text
    if status_code == 409:
        assert response.json()["code"] == "SLOT_UNAVAILABLE"


async def test_create_overlapping_an_own_booking_at_another_table_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    assert (await book(client, venue.four.id, at(TOMORROW, 12))).status_code == 201

    overlapping = await book(client, venue.other.id, at(TOMORROW, 12, 30))
    adjacent = await book(client, venue.other.id, at(TOMORROW, 13, 30))

    assert_error(overlapping, 409, "OVERLAPPING_BOOKING")
    assert adjacent.status_code == 201, adjacent.text
    assert await count_bookings(connection) == 2


@pytest.mark.parametrize(
    ("table", "party_size", "status_code", "code"),
    [
        (None, 2, 404, "TABLE_NOT_FOUND"),
        ("small", 3, 400, "TABLE_NOT_SUITABLE"),
        ("six", 2, 400, "TABLE_NOT_SUITABLE"),
        ("eight", 4, 400, "TABLE_NOT_SUITABLE"),
    ],
)
async def test_create_on_a_wrong_table_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    table: str | None,
    party_size: int,
    status_code: int,
    code: str,
) -> None:
    table_id = uuid.uuid4() if table is None else getattr(venue, table).id
    await sign_in(client, ADA)

    response = await book(client, table_id, at(TOMORROW, 12), party_size=party_size)

    assert_error(response, status_code, code)
    assert await count_bookings(connection) == 0


async def test_create_reports_the_first_failing_check(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    unknown = uuid.uuid4()
    far_off_grid = at(TODAY + timedelta(days=31), 12, 15)

    assert_error(await book(client, unknown, far_off_grid, party_size=5), 401, "NOT_AUTHENTICATED")
    await sign_in(client, ADA)
    assert_error(await book(client, unknown, far_off_grid, party_size=5), 400, "PARTY_TOO_LARGE")
    assert_error(await book(client, unknown, far_off_grid), 400, "DATE_OUT_OF_RANGE")
    assert_error(await book(client, unknown, at(TOMORROW, 12, 15)), 400, "SLOT_INVALID")
    assert_error(await book(client, unknown, at(TODAY, 13)), 404, "TABLE_NOT_FOUND")
    assert_error(await book(client, venue.six.id, at(TODAY, 13)), 400, "TABLE_NOT_SUITABLE")
    await add_booking(
        session_factory, user=users[ADA], table=venue.other, starts_at=at(TODAY, 12, 30)
    )
    assert_error(await book(client, venue.four.id, at(TODAY, 13)), 409, "SLOT_UNAVAILABLE")
    assert (await book(client, venue.four.id, at(TOMORROW, 12))).status_code == 201
    assert_error(await book(client, venue.four.id, at(TOMORROW, 12, 30)), 409, "SLOT_UNAVAILABLE")


@pytest.mark.parametrize(
    ("method", "path"), [("get", BOOKINGS), ("post", f"{BOOKINGS}/{uuid.uuid4()}/cancel")]
)
async def test_booking_routes_need_sign_in(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)

    assert_error(response, 401, "NOT_AUTHENTICATED")


async def test_list_returns_own_bookings_in_every_status_newest_start_first(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=at(TOMORROW, 12)
    )
    await sign_in(client, ADA)
    earliest = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    middle = (await book(client, venue.other.id, at(TOMORROW, 18))).json()
    latest = (await book(client, venue.small.id, at(TOMORROW + timedelta(days=1), 12))).json()
    cancelled = (await cancel(client, latest["id"])).json()

    response = await client.get(BOOKINGS)

    assert response.status_code == 200, response.text
    assert response.json() == [cancelled, middle, earliest]
    assert cancelled["status"] == "CANCELLED"


async def test_list_breaks_equal_starts_by_id(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    first = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    await cancel(client, first["id"])
    second = (await book(client, venue.small.id, at(TOMORROW, 12))).json()

    response = await client.get(BOOKINGS)

    assert [booking["id"] for booking in response.json()] == sorted(
        [first["id"], second["id"]], key=uuid.UUID
    )


async def test_cancel_frees_the_slot(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await cancel(client, created["id"])

    assert response.status_code == 200, response.text
    assert response.json() == {**created, "status": "CANCELLED"}
    assert await stored_status(connection, created["id"]) == BookingStatus.CANCELLED
    assert all(availability(await search(client), venue.four).values())
    await sign_in(client, GRACE)
    rebooked = await book(client, venue.four.id, at(TOMORROW, 12))
    assert rebooked.status_code == 201, rebooked.text


async def test_cancel_of_an_unknown_or_foreign_booking_is_not_found(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    await sign_in(client, GRACE)

    foreign = await cancel(client, created["id"])
    unknown = await cancel(client, uuid.uuid4())

    assert_error(foreign, 404, "BOOKING_NOT_FOUND")
    assert_error(unknown, 404, "BOOKING_NOT_FOUND")
    assert await stored_status(connection, created["id"]) == BookingStatus.CONFIRMED


async def test_cancel_twice_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    assert (await cancel(client, created["id"])).status_code == 200

    assert_error(await cancel(client, created["id"]), 409, "BOOKING_ALREADY_CANCELLED")


@pytest.mark.parametrize(("minutes", "status_code"), [(20, 200), (21, 409)])
async def test_cancel_closes_shortly_before_the_start(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    minutes: int,
    status_code: int,
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TODAY, 14))).json()
    fake_clock.advance(minutes=minutes)
    await sign_in(client, ADA)

    response = await cancel(client, created["id"])

    assert response.status_code == status_code, response.text
    if status_code == 409:
        assert response.json()["code"] == "CANCELLATION_CLOSED"
        assert await stored_status(connection, created["id"]) == BookingStatus.CONFIRMED


async def test_cancel_reports_the_first_failing_check(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cancelled_soon = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.four,
        starts_at=at(TODAY, 13, 30),
        status=BookingStatus.CANCELLED,
    )

    assert_error(await cancel(client, cancelled_soon.id), 401, "NOT_AUTHENTICATED")
    await sign_in(client, GRACE)
    assert_error(await cancel(client, cancelled_soon.id), 404, "BOOKING_NOT_FOUND")
    await sign_in(client, ADA)
    assert_error(await cancel(client, cancelled_soon.id), 409, "BOOKING_ALREADY_CANCELLED")
