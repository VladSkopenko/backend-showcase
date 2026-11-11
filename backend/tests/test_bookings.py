import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    SEARCH,
    START,
    TODAY,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    as_guest,
    assert_error,
    at,
    book,
    cancel,
    edit,
    grid,
    location_body,
    sign_in,
    stored_participants,
)

from app.common import clock
from app.config.settings import BookingSettings, Settings, get_settings
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.main import create_app
from app.model_registry import Booking, BookingParticipant, DiningTable, Guest, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]


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


async def add_guest(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    token: str,
    expires_at: datetime = START + timedelta(days=31),
) -> Guest:
    guest = Guest(
        name=name, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires_at
    )
    async with session_factory() as session:
        session.add(guest)
        await session.commit()
    return guest


async def add_participant(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    booking_id: str | uuid.UUID,
    user: User | None = None,
    guest: Guest | None = None,
) -> BookingParticipant:
    participant = BookingParticipant(
        booking_id=uuid.UUID(str(booking_id)),
        user_id=None if user is None else user.id,
        guest_id=None if guest is None else guest.id,
        role=ParticipantRole.GUEST,
        created_at=clock.now(),
    )
    async with session_factory() as session:
        session.add(participant)
        await session.commit()
    return participant


async def search(client: httpx2.AsyncClient, **params: Any) -> httpx2.Response:
    return await client.get(SEARCH, params={"date": str(TOMORROW), "party_size": 2, **params})


async def edit_slots(
    client: httpx2.AsyncClient, booking_id: str | uuid.UUID, duration_minutes: int
) -> httpx2.Response:
    return await client.get(
        f"{BOOKINGS}/{booking_id}/slots", params={"duration_minutes": duration_minutes}
    )


def card_ids(response: httpx2.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [card["id"] for card in response.json()["items"]]


def availability(response: httpx2.Response, table: DiningTable) -> dict[datetime, bool]:
    [card] = [card for card in response.json()["items"] if card["id"] == str(table.id)]
    return {datetime.fromisoformat(slot["starts_at"]): slot["available"] for slot in card["slots"]}


async def count_bookings(connection: AsyncConnection) -> int:
    count = await connection.scalar(select(func.count()).select_from(Booking))
    assert count is not None
    return count


async def stored_period(
    connection: AsyncConnection, booking_id: str | uuid.UUID
) -> tuple[datetime, datetime, int]:
    row = (
        await connection.execute(
            select(Booking.starts_at, Booking.ends_at, Booking.party_size).where(
                Booking.id == uuid.UUID(str(booking_id))
            )
        )
    ).one()
    return row[0], row[1], row[2]


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
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TOMORROW, 12))

    assert response.status_code == 201, response.text
    body = response.json()
    [owner] = body["participants"]
    assert body == {
        "id": body["id"],
        "status": "CONFIRMED",
        "party_size": 2,
        "starts_at": "2026-11-13T12:00:00+04:00",
        "ends_at": "2026-11-13T13:30:00+04:00",
        "table": {"id": str(venue.four.id), "label": "Table 2", "capacity": 4},
        "location": location_body(venue.first),
        "role": "OWNER",
        "participants": [{"id": owner["id"], "name": "Ada", "role": "OWNER"}],
    }
    assert await stored_participants(connection, body["id"]) == [
        (users[ADA].id, None, ParticipantRole.OWNER)
    ]
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
    ("method", "path"),
    [
        ("get", BOOKINGS),
        ("post", f"{BOOKINGS}/{uuid.uuid4()}/cancel"),
        ("put", f"{BOOKINGS}/{uuid.uuid4()}"),
        ("get", f"{BOOKINGS}/{uuid.uuid4()}/slots"),
        ("get", f"{BOOKINGS}/{uuid.uuid4()}"),
    ],
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


async def test_edit_to_a_longer_stay_blocks_the_extra_starts_and_back_frees_them(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    longer = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=180)

    assert longer.status_code == 200, longer.text
    assert longer.json() == {**created, "ends_at": "2026-11-13T15:00:00+04:00"}
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 15),
        2,
    )
    after_hours = [at(TOMORROW, 13, 30), at(TOMORROW, 14), at(TOMORROW, 14, 30)]
    extended = availability(await search(client), venue.four)
    assert [extended[start] for start in after_hours] == [False, False, False]
    assert extended[at(TOMORROW, 15)] is True
    shorter = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=90)
    assert shorter.status_code == 200, shorter.text
    assert shorter.json() == created
    restored = availability(await search(client), venue.four)
    assert [restored[start] for start in after_hours] == [True, True, True]


async def test_edit_moves_the_booking_and_frees_the_old_start(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 14), party_size=2)

    assert response.status_code == 200, response.text
    moved = {
        **created,
        "starts_at": "2026-11-13T14:00:00+04:00",
        "ends_at": "2026-11-13T15:30:00+04:00",
    }
    assert response.json() == moved
    assert (await client.get(BOOKINGS)).json() == [moved]
    found = availability(await search(client), venue.four)
    assert found[at(TOMORROW, 12)] is True
    assert found[at(TOMORROW, 13)] is False


async def test_edit_may_end_exactly_at_closing(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 21, 30), duration_minutes=90)

    assert response.status_code == 200, response.text
    assert response.json()["ends_at"] == "2026-11-13T23:00:00+04:00"


@pytest.mark.parametrize(("minutes", "status_code"), [(20, 200), (21, 409)])
async def test_edit_closes_at_the_cancel_cutoff(
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

    response = await edit(client, created["id"], at(TODAY, 14), duration_minutes=120)

    assert response.status_code == status_code, response.text
    if status_code == 200:
        assert await stored_period(connection, created["id"]) == (
            at(TODAY, 14),
            at(TODAY, 16),
            2,
        )
    else:
        assert response.json()["code"] == "EDIT_CLOSED"
        assert await stored_period(connection, created["id"]) == (
            at(TODAY, 14),
            at(TODAY, 15, 30),
            2,
        )


async def test_edit_to_a_start_already_past_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TODAY, 15))).json()

    response = await edit(client, created["id"], at(TODAY, 13))

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert await stored_period(connection, created["id"]) == (
        at(TODAY, 15),
        at(TODAY, 16, 30),
        2,
    )


async def test_edit_over_its_own_old_range_succeeds(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 12, 30), duration_minutes=120)

    assert response.status_code == 200, response.text
    assert response.json()["starts_at"] == "2026-11-13T12:30:00+04:00"
    assert response.json()["ends_at"] == "2026-11-13T14:30:00+04:00"


@pytest.mark.parametrize(("table", "status_code"), [("four", 200), ("small", 400)])
async def test_edit_party_size_must_fit_the_table(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    table: str,
    status_code: int,
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, getattr(venue, table).id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 12), party_size=4)

    assert response.status_code == status_code, response.text
    if status_code == 200:
        assert response.json() == {**created, "party_size": 4}
    else:
        assert response.json()["code"] == "TABLE_NOT_SUITABLE"
        assert await stored_period(connection, created["id"]) == (
            at(TOMORROW, 12),
            at(TOMORROW, 13, 30),
            2,
        )


@pytest.mark.parametrize(
    ("starts_at", "party_size", "duration_minutes", "code"),
    [
        (at(TOMORROW, 21), 2, 150, "ENDS_AFTER_CLOSING"),
        (at(TOMORROW, 21, 30), 2, 120, "ENDS_AFTER_CLOSING"),
        (at(TOMORROW, 12), 2, 100, "DURATION_INVALID"),
        (at(TOMORROW, 12), 2, 210, "DURATION_INVALID"),
        (at(TOMORROW, 12), 2, 60, "DURATION_INVALID"),
        (at(TOMORROW + timedelta(days=1), 12), 2, 90, "DAY_CHANGE_NOT_ALLOWED"),
        (at(TODAY, 15), 2, 90, "DAY_CHANGE_NOT_ALLOWED"),
        (at(TOMORROW, 12, 15), 2, 90, "SLOT_INVALID"),
        (at(TOMORROW, 9, 30), 2, 90, "SLOT_INVALID"),
        (at(TOMORROW, 22), 2, 90, "SLOT_INVALID"),
        (at(TOMORROW, 12), 5, 90, "PARTY_TOO_LARGE"),
    ],
)
async def test_bad_edit_input_changes_nothing(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    starts_at: datetime,
    party_size: int,
    duration_minutes: int,
    code: str,
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(
        client, created["id"], starts_at, party_size=party_size, duration_minutes=duration_minutes
    )

    assert_error(response, 400, code)
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_with_party_size_zero_is_a_validation_error(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 12), party_size=0)

    assert_error(response, 422, "VALIDATION_ERROR")


async def test_edit_onto_a_range_taken_on_the_table_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 14, 30)
    )
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    longer = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=180)
    moved = await edit(client, created["id"], at(TOMORROW, 14))

    assert_error(longer, 409, "SLOT_UNAVAILABLE")
    assert_error(moved, 409, "SLOT_UNAVAILABLE")
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_up_to_the_next_booking_on_the_table_succeeds(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 15)
    )
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=180)

    assert response.status_code == 200, response.text


async def test_edit_onto_a_cancelled_booking_range_succeeds(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.four,
        starts_at=at(TOMORROW, 14, 30),
        status=BookingStatus.CANCELLED,
    )
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=180)

    assert response.status_code == 200, response.text
    assert response.json()["ends_at"] == "2026-11-13T15:00:00+04:00"


async def test_edit_overlapping_another_own_booking_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    assert (await book(client, venue.other.id, at(TOMORROW, 14))).status_code == 201

    response = await edit(client, created["id"], at(TOMORROW, 12), duration_minutes=180)

    assert_error(response, 409, "OVERLAPPING_BOOKING")
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_of_an_unknown_or_foreign_booking_is_not_found(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    await sign_in(client, GRACE)

    foreign = await edit(client, created["id"], at(TOMORROW, 14))
    unknown = await edit(client, uuid.uuid4(), at(TOMORROW, 14))

    assert_error(foreign, 404, "BOOKING_NOT_FOUND")
    assert_error(unknown, 404, "BOOKING_NOT_FOUND")
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_of_a_cancelled_booking_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    assert (await cancel(client, created["id"])).status_code == 200

    response = await edit(client, created["id"], at(TOMORROW, 14))

    assert_error(response, 409, "BOOKING_ALREADY_CANCELLED")
    assert await stored_status(connection, created["id"]) == BookingStatus.CANCELLED
    assert await stored_period(connection, created["id"]) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_converts_a_start_sent_with_another_offset_to_the_local_day(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], "2026-11-12T22:00:00-08:00")

    assert response.status_code == 200, response.text
    assert response.json()["starts_at"] == "2026-11-13T10:00:00+04:00"
    assert response.json()["ends_at"] == "2026-11-13T11:30:00+04:00"


async def test_edit_to_an_offset_that_lands_on_the_next_local_day_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await edit(client, created["id"], "2026-11-13T22:00:00-08:00")

    assert_error(response, 400, "DAY_CHANGE_NOT_ALLOWED")


async def test_edit_reports_the_first_failing_check(
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
    closed = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TODAY, 13, 30)
    )
    target = await add_booking(
        session_factory, user=users[ADA], table=venue.small, starts_at=at(TODAY, 15)
    )
    await add_booking(
        session_factory, user=users[GRACE], table=venue.small, starts_at=at(TODAY, 18)
    )
    await add_booking(
        session_factory, user=users[ADA], table=venue.other, starts_at=at(TODAY, 17, 30)
    )
    next_day_off_grid = at(TOMORROW, 15, 15)

    assert_error(await edit(client, target.id, next_day_off_grid, 5, 100), 401, "NOT_AUTHENTICATED")
    await sign_in(client, GRACE)
    assert_error(await edit(client, target.id, next_day_off_grid, 5, 100), 404, "BOOKING_NOT_FOUND")
    await sign_in(client, ADA)
    assert_error(
        await edit(client, cancelled_soon.id, next_day_off_grid, 5, 100),
        409,
        "BOOKING_ALREADY_CANCELLED",
    )
    assert_error(await edit(client, closed.id, next_day_off_grid, 5, 100), 409, "EDIT_CLOSED")
    assert_error(await edit(client, target.id, next_day_off_grid, 5, 100), 400, "PARTY_TOO_LARGE")
    assert_error(
        await edit(client, target.id, next_day_off_grid, 4, 100), 400, "DAY_CHANGE_NOT_ALLOWED"
    )
    assert_error(await edit(client, target.id, at(TODAY, 15, 15), 4, 100), 400, "SLOT_INVALID")
    assert_error(await edit(client, target.id, at(TODAY, 21, 30), 4, 100), 400, "DURATION_INVALID")
    assert_error(
        await edit(client, target.id, at(TODAY, 21, 30), 4, 120), 400, "ENDS_AFTER_CLOSING"
    )
    assert_error(await edit(client, target.id, at(TODAY, 13), 4, 90), 400, "TABLE_NOT_SUITABLE")
    assert_error(await edit(client, target.id, at(TODAY, 13), 2, 90), 409, "SLOT_UNAVAILABLE")
    assert_error(await edit(client, target.id, at(TODAY, 18), 2, 90), 409, "SLOT_UNAVAILABLE")
    assert_error(
        await edit(client, target.id, at(TODAY, 16, 30), 2, 90), 409, "OVERLAPPING_BOOKING"
    )


async def test_slots_for_a_longer_stay_ignore_the_booking_itself_and_respect_closing(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.four, starts_at=at(TOMORROW, 15)
    )
    await add_booking(
        session_factory, user=users[GRACE], table=venue.small, starts_at=at(TOMORROW, 10)
    )
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    assert (await book(client, venue.other.id, at(TOMORROW, 17))).status_code == 201

    response = await edit_slots(client, created["id"], 180)

    assert response.status_code == 200, response.text
    free = {at(TOMORROW, 10) + timedelta(minutes=30 * step) for step in range(5)}
    free |= {at(TOMORROW, 16, 30) + timedelta(minutes=30 * step) for step in range(8)}
    assert response.json() == [
        {"starts_at": start.isoformat(), "available": start in free} for start in grid(TOMORROW)
    ]


async def test_slots_today_mark_starts_up_to_now_unavailable(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TODAY, 15))).json()

    response = await edit_slots(client, created["id"], 90)

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"starts_at": start.isoformat(), "available": start > at(TODAY, 13, 10)}
        for start in grid(TODAY)
    ]


async def test_slots_of_an_unknown_or_foreign_booking_are_not_found(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    await sign_in(client, GRACE)

    assert_error(await edit_slots(client, created["id"], 90), 404, "BOOKING_NOT_FOUND")
    assert_error(await edit_slots(client, uuid.uuid4(), 90), 404, "BOOKING_NOT_FOUND")


async def test_slots_report_the_first_failing_check(
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
    closed = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TODAY, 13, 30)
    )
    target = await add_booking(
        session_factory, user=users[ADA], table=venue.small, starts_at=at(TOMORROW, 12)
    )

    assert_error(await edit_slots(client, target.id, 100), 401, "NOT_AUTHENTICATED")
    await sign_in(client, GRACE)
    assert_error(await edit_slots(client, target.id, 100), 404, "BOOKING_NOT_FOUND")
    await sign_in(client, ADA)
    assert_error(await edit_slots(client, cancelled_soon.id, 100), 409, "BOOKING_ALREADY_CANCELLED")
    assert_error(await edit_slots(client, closed.id, 100), 409, "EDIT_CLOSED")
    assert_error(await edit_slots(client, target.id, 100), 400, "DURATION_INVALID")
    assert_error(await edit_slots(client, target.id, 210), 400, "DURATION_INVALID")


async def test_search_marks_starts_that_would_end_after_closing_unavailable(
    client: httpx2.AsyncClient, app: FastAPI, venue: Venue
) -> None:
    settings = Settings(booking=BookingSettings(closing_time=time(22, 30)))
    app.dependency_overrides[get_settings] = lambda: settings

    response = await search(client)

    assert availability(response, venue.four) == {
        start: start <= at(TOMORROW, 21) for start in grid(TOMORROW)
    }


async def test_list_includes_joined_bookings_with_the_callers_role(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    joined = await add_booking(
        session_factory, user=users[GRACE], table=venue.other, starts_at=at(TOMORROW, 18)
    )
    await add_participant(session_factory, booking_id=joined.id, user=users[ADA])
    await add_booking(
        session_factory, user=users[GRACE], table=venue.small, starts_at=at(TOMORROW, 20)
    )
    await sign_in(client, ADA)
    owned = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    response = await client.get(BOOKINGS)

    assert response.status_code == 200, response.text
    first, second = response.json()
    assert first["id"] == str(joined.id)
    assert first["role"] == "GUEST"
    assert [(p["name"], p["role"]) for p in first["participants"]] == [
        ("Grace", "OWNER"),
        ("Ada", "GUEST"),
    ]
    assert second == owned


async def test_participant_view_answers_every_participant_with_their_role(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    fake_clock: FakeClock,
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12), party_size=3
    )
    fake_clock.advance(minutes=2)
    alex = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=booking.id, guest=alex)
    fake_clock.current = START + timedelta(minutes=1)
    await add_participant(session_factory, booking_id=booking.id, user=users[GRACE])
    await sign_in(client, ADA)

    as_owner = await client.get(f"{BOOKINGS}/{booking.id}")
    await sign_in(client, GRACE)
    as_user = await client.get(f"{BOOKINGS}/{booking.id}")
    client.cookies.clear()
    as_guest_of_it = await client.get(f"{BOOKINGS}/{booking.id}", headers=as_guest("alex-token"))

    assert as_owner.status_code == 200, as_owner.text
    body = as_owner.json()
    assert body == {
        "id": str(booking.id),
        "status": "CONFIRMED",
        "party_size": 3,
        "starts_at": "2026-11-13T12:00:00+04:00",
        "ends_at": "2026-11-13T13:30:00+04:00",
        "table": {"id": str(venue.four.id), "label": "Table 2", "capacity": 4},
        "location": location_body(venue.first),
        "role": "OWNER",
        "participants": body["participants"],
    }
    assert [(p["name"], p["role"]) for p in body["participants"]] == [
        ("Ada", "OWNER"),
        ("Grace", "GUEST"),
        ("Alex", "GUEST"),
    ]
    assert as_user.json() == {**body, "role": "GUEST"}
    assert as_guest_of_it.status_code == 200, as_guest_of_it.text
    assert as_guest_of_it.json() == {**body, "role": "GUEST"}


@pytest.mark.parametrize("token", [None, "unknown-token", "expired-token"])
async def test_participant_view_without_a_user_or_a_valid_guest_is_not_authenticated(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    token: str | None,
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    expired = await add_guest(session_factory, name="Alex", token="expired-token", expires_at=START)
    await add_participant(session_factory, booking_id=booking.id, guest=expired)

    response = await client.get(
        f"{BOOKINGS}/{booking.id}", headers={} if token is None else as_guest(token)
    )

    assert_error(response, 401, "NOT_AUTHENTICATED")


async def test_participant_view_of_a_booking_one_did_not_join_is_not_found(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    other = await add_booking(
        session_factory, user=users[ADA], table=venue.other, starts_at=at(TOMORROW, 18)
    )
    alex = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=booking.id, guest=alex)
    bea = await add_guest(session_factory, name="Bea", token="bea-token")
    await add_participant(session_factory, booking_id=other.id, guest=bea)
    await sign_in(client, GRACE)
    access_token = client.cookies["access_token"]

    stranger = await client.get(f"{BOOKINGS}/{booking.id}")
    client.cookies.clear()
    stranger_with_guest_cookie = await client.get(
        f"{BOOKINGS}/{booking.id}",
        headers={"Cookie": f"access_token={access_token}; guest_token=alex-token"},
    )
    guest_of_another = await client.get(f"{BOOKINGS}/{booking.id}", headers=as_guest("bea-token"))
    await sign_in(client, ADA)
    unknown = await client.get(f"{BOOKINGS}/{uuid.uuid4()}")

    assert_error(stranger, 404, "BOOKING_NOT_FOUND")
    assert_error(stranger_with_guest_cookie, 404, "BOOKING_NOT_FOUND")
    assert_error(guest_of_another, 404, "BOOKING_NOT_FOUND")
    assert_error(unknown, 404, "BOOKING_NOT_FOUND")


async def test_a_joined_user_can_neither_edit_nor_cancel(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    await add_participant(session_factory, booking_id=booking.id, user=users[GRACE])
    await sign_in(client, GRACE)

    assert_error(await edit(client, booking.id, at(TOMORROW, 14)), 404, "BOOKING_NOT_FOUND")
    assert_error(await cancel(client, booking.id), 404, "BOOKING_NOT_FOUND")
    assert_error(await edit_slots(client, booking.id, 90), 404, "BOOKING_NOT_FOUND")
    assert await stored_status(connection, booking.id) == BookingStatus.CONFIRMED
    assert await stored_period(connection, booking.id) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        2,
    )


async def test_edit_refuses_a_party_below_the_participant_count(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12), party_size=3
    )
    await add_participant(session_factory, booking_id=booking.id, user=users[GRACE])
    fake_clock.advance(minutes=1)
    alex = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=booking.id, guest=alex)
    await sign_in(client, ADA)

    smaller = await edit(client, booking.id, at(TOMORROW, 12), party_size=2)

    assert_error(smaller, 409, "PARTY_BELOW_PARTICIPANTS")
    assert await stored_period(connection, booking.id) == (
        at(TOMORROW, 12),
        at(TOMORROW, 13, 30),
        3,
    )
    same = await edit(client, booking.id, at(TOMORROW, 12), party_size=3)
    assert same.status_code == 200, same.text
    assert [(p["name"], p["role"]) for p in same.json()["participants"]] == [
        ("Ada", "OWNER"),
        ("Grace", "GUEST"),
        ("Alex", "GUEST"),
    ]


async def test_cancel_answers_the_booking_with_its_participants(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    alex = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=booking.id, guest=alex)
    await sign_in(client, ADA)

    response = await cancel(client, booking.id)

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "OWNER"
    assert [(p["name"], p["role"]) for p in response.json()["participants"]] == [
        ("Ada", "OWNER"),
        ("Alex", "GUEST"),
    ]


async def test_participant_view_with_an_invalid_access_cookie_is_not_authenticated(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=at(TOMORROW, 12)
    )
    alex = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=booking.id, guest=alex)

    response = await client.get(
        f"{BOOKINGS}/{booking.id}",
        headers={"Cookie": "access_token=not-a-token; guest_token=alex-token"},
    )

    assert_error(response, 401, "NOT_AUTHENTICATED")


async def test_edit_checks_the_participants_after_the_input_and_before_the_overlaps(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.small, starts_at=at(TOMORROW, 12)
    )
    await add_participant(session_factory, booking_id=booking.id, user=users[GRACE])
    await add_booking(
        session_factory, user=users[GRACE], table=venue.small, starts_at=at(TOMORROW, 14, 30)
    )
    await add_booking(
        session_factory, user=users[ADA], table=venue.other, starts_at=at(TOMORROW, 17)
    )
    await sign_in(client, ADA)

    assert_error(
        await edit(client, booking.id, at(TOMORROW, 12), party_size=3), 400, "TABLE_NOT_SUITABLE"
    )
    assert_error(
        await edit(client, booking.id, at(TOMORROW, 14), party_size=1),
        409,
        "PARTY_BELOW_PARTICIPANTS",
    )
    assert_error(
        await edit(client, booking.id, at(TOMORROW, 16, 30), party_size=1),
        409,
        "PARTY_BELOW_PARTICIPANTS",
    )
    assert_error(await edit(client, booking.id, at(TOMORROW, 14)), 409, "SLOT_UNAVAILABLE")
