import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    DURATION,
    GRACE,
    SEARCH,
    TODAY,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    assert_error,
    at,
    book,
    cancel,
    edit,
    grid,
    sign_in,
)

from app.config.settings import Settings, get_settings
from app.features.core.bookings.enums import BookingStatus
from app.main import create_app
from app.model_registry import Booking, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

INVITES = "/api/v1/invites"
NOON = at(TOMORROW, 12)


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


async def count_bookings(connection: AsyncConnection) -> int:
    count = await connection.scalar(select(func.count()).select_from(Booking))
    assert count is not None
    return count


async def stored_booking(
    connection: AsyncConnection, booking_id: str | uuid.UUID
) -> tuple[BookingStatus, datetime, int]:
    row = (
        await connection.execute(
            select(Booking.status, Booking.starts_at, Booking.party_size).where(
                Booking.id == uuid.UUID(str(booking_id))
            )
        )
    ).one()
    return row[0], row[1], row[2]


async def request(
    client: httpx2.AsyncClient, table_id: uuid.UUID, starts_at: datetime, party_size: int = 6
) -> dict[str, str]:
    response = await book(client, table_id, starts_at, party_size=party_size)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    created: dict[str, str] = response.json()
    return created


async def test_a_large_party_sends_a_pending_request(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.six.id, NOON, party_size=6)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["party_size"] == 6
    assert body["table"] == {"id": str(venue.six.id), "label": "Table 3", "capacity": 6}
    assert await stored_booking(connection, body["id"]) == (BookingStatus.PENDING, NOON, 6)


async def test_the_smallest_party_above_the_instant_limit_sends_a_request(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.six.id, NOON, party_size=5)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    assert await stored_booking(connection, response.json()["id"]) == (
        BookingStatus.PENDING,
        NOON,
        5,
    )


@pytest.mark.parametrize(
    ("table_name", "party_size", "hour", "minute", "expected"),
    [
        ("six", 6, 14, 0, "REQUEST_TOO_LATE"),
        ("six", 6, 15, 0, "REQUEST_TOO_LATE"),
        ("six", 6, 15, 30, "PENDING"),
        ("four", 2, 14, 0, "CONFIRMED"),
    ],
)
async def test_a_request_must_start_beyond_the_auto_reject_lead(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    table_name: str,
    party_size: int,
    hour: int,
    minute: int,
    expected: str,
) -> None:
    # 15:00 is exactly the default lead of 120 minutes away.
    fake_clock.current = at(TODAY, 13)
    await sign_in(client, ADA)

    response = await book(
        client, getattr(venue, table_name).id, at(TODAY, hour, minute), party_size=party_size
    )

    if expected == "REQUEST_TOO_LATE":
        assert_error(response, 409, "REQUEST_TOO_LATE")
        assert await count_bookings(connection) == 0
    else:
        assert response.status_code == 201, response.text
        assert response.json()["status"] == expected


async def test_two_users_may_request_the_same_table_and_start(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    first = await request(client, venue.eight.id, at(TOMORROW, 19), party_size=8)
    await sign_in(client, GRACE)
    second = await request(client, venue.eight.id, at(TOMORROW, 19), party_size=6)

    assert first["id"] != second["id"]
    assert await count_bookings(connection) == 2


async def test_a_request_on_a_table_with_a_confirmed_overlap_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await add_booking(
        session_factory, user=users[GRACE], table=venue.six, starts_at=NOON, party_size=6
    )
    await sign_in(client, ADA)

    response = await book(client, venue.six.id, at(TOMORROW, 12, 30), party_size=6)

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert await count_bookings(connection) == 1


async def test_a_party_above_the_request_limit_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.eight.id, NOON, party_size=9)

    assert_error(response, 400, "PARTY_TOO_LARGE")
    assert await count_bookings(connection) == 0


async def test_a_request_on_a_too_small_table_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, NOON, party_size=5)

    assert_error(response, 400, "TABLE_NOT_SUITABLE")
    assert await count_bookings(connection) == 0


async def test_an_instant_booking_on_a_request_only_table_is_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)

    response = await book(client, venue.six.id, NOON, party_size=4)

    assert_error(response, 400, "TABLE_NOT_SUITABLE")
    assert await count_bookings(connection) == 0


async def test_a_pending_request_blocks_the_users_overlapping_bookings_and_requests(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    await request(client, venue.six.id, NOON)
    later = await book(client, venue.four.id, at(TOMORROW, 15))
    assert later.status_code == 201, later.text

    assert_error(
        await book(client, venue.four.id, at(TOMORROW, 12, 30)), 409, "OVERLAPPING_BOOKING"
    )
    assert_error(
        await book(client, venue.eight.id, at(TOMORROW, 13), party_size=6),
        409,
        "OVERLAPPING_BOOKING",
    )
    assert_error(
        await edit(client, later.json()["id"], at(TOMORROW, 13)), 409, "OVERLAPPING_BOOKING"
    )
    assert await count_bookings(connection) == 2
    assert await stored_booking(connection, later.json()["id"]) == (
        BookingStatus.CONFIRMED,
        at(TOMORROW, 15),
        2,
    )


async def test_a_confirmed_booking_blocks_the_users_overlapping_request(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    booked = await book(client, venue.four.id, NOON)
    assert booked.status_code == 201, booked.text

    response = await book(client, venue.six.id, at(TOMORROW, 12, 30), party_size=6)

    assert_error(response, 409, "OVERLAPPING_BOOKING")
    assert await count_bookings(connection) == 1


async def test_search_for_the_smallest_request_party_lists_only_request_tables(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    response = await client.get(SEARCH, params={"date": str(TOMORROW), "party_size": 5})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [
        str(venue.six.id),
        str(venue.eight.id),
    ]


async def test_search_for_a_large_party_blocks_only_confirmed_starts(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    confirmed = at(TOMORROW, 18)
    await add_booking(
        session_factory, user=users[GRACE], table=venue.six, starts_at=confirmed, party_size=6
    )
    await sign_in(client, ADA)
    await request(client, venue.six.id, NOON)
    client.cookies.clear()

    response = await client.get(SEARCH, params={"date": str(TOMORROW), "party_size": 6})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(venue.six.id), str(venue.eight.id)]
    assert items[0]["slots"] == [
        {
            "starts_at": start.isoformat(),
            "available": not (start < confirmed + DURATION and start + DURATION > confirmed),
        }
        for start in grid(TOMORROW)
    ]
    assert {"starts_at": NOON.isoformat(), "available": True} in items[0]["slots"]
    assert {"starts_at": confirmed.isoformat(), "available": False} in items[0]["slots"]


async def test_a_pending_request_cannot_be_edited(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)

    response = await edit(client, created["id"], at(TOMORROW, 14), party_size=2)

    assert_error(response, 409, "BOOKING_PENDING")
    assert await stored_booking(connection, created["id"]) == (BookingStatus.PENDING, NOON, 6)


async def test_the_edit_slots_of_a_pending_request_are_refused(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)

    response = await client.get(
        f"{BOOKINGS}/{created['id']}/slots", params={"duration_minutes": 90}
    )

    assert_error(response, 409, "BOOKING_PENDING")


async def test_a_pending_request_can_be_cancelled(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)

    response = await cancel(client, created["id"])

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert (await stored_booking(connection, created["id"]))[0] == BookingStatus.CANCELLED


async def test_a_pending_request_cannot_be_cancelled_after_the_cutoff(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, at(TODAY, 16))
    fake_clock.advance(hours=2, minutes=25)
    await sign_in(client, ADA)

    response = await cancel(client, created["id"])

    assert_error(response, 409, "CANCELLATION_CLOSED")
    assert (await stored_booking(connection, created["id"]))[0] == BookingStatus.PENDING


async def test_a_withdrawn_request_frees_the_user_and_is_closed(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)
    assert (await cancel(client, created["id"])).status_code == 200

    booked = await book(client, venue.four.id, at(TOMORROW, 12, 30))

    assert booked.status_code == 201, booked.text
    assert_error(await cancel(client, created["id"]), 409, "BOOKING_ALREADY_CANCELLED")
    assert_error(
        await edit(client, created["id"], at(TOMORROW, 14)), 409, "BOOKING_ALREADY_CANCELLED"
    )
    assert_error(
        await client.get(f"{BOOKINGS}/{created['id']}/slots", params={"duration_minutes": 90}),
        409,
        "BOOKING_ALREADY_CANCELLED",
    )


async def test_pre_order_stays_closed_while_the_request_is_pending(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)

    response = await client.put(
        f"{BOOKINGS}/{created['id']}/cart/items/{uuid.uuid4()}", json={"quantity": 1}
    )

    assert_error(response, 409, "PREORDER_CLOSED")


async def test_friends_can_preview_and_join_a_pending_request(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = await request(client, venue.six.id, NOON)
    link = await client.get(f"{BOOKINGS}/{created['id']}/invite")
    assert link.status_code == 200, link.text
    code = link.json()["code"]
    await sign_in(client, GRACE)

    preview = await client.get(f"{INVITES}/{code}")
    joined = await client.post(f"{INVITES}/{code}/join")

    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "PENDING"
    assert joined.status_code == 200, joined.text
    assert joined.json()["status"] == "PENDING"
    assert joined.json()["role"] == "GUEST"
