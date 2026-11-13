import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    BOOKINGS,
    GRACE,
    SEARCH,
    STAFF,
    START,
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
    location_body,
    sign_in,
)

from app.config.settings import Settings, get_settings
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.repositories import BookingRepository
from app.features.core.menu.enums import DishCategory
from app.main import create_app
from app.model_registry import Booking, DiningTable, Dish, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

REQUESTS = "/api/v1/staff/booking-requests"
INVITES = "/api/v1/invites"
EVENING = at(TOMORROW, 19)


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


async def request(
    client: httpx2.AsyncClient, table_id: uuid.UUID, starts_at: datetime, party_size: int = 6
) -> str:
    response = await book(client, table_id, starts_at, party_size=party_size)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    booking_id: str = response.json()["id"]
    return booking_id


async def decide(client: httpx2.AsyncClient, booking_id: str | uuid.UUID, action: str) -> Any:
    return await client.post(f"{REQUESTS}/{booking_id}/{action}")


async def stored_decision(
    connection: AsyncConnection, booking_id: str | uuid.UUID
) -> tuple[BookingStatus, datetime | None, uuid.UUID | None]:
    row = (
        await connection.execute(
            select(Booking.status, Booking.decided_at, Booking.decided_by_id).where(
                Booking.id == uuid.UUID(str(booking_id))
            )
        )
    ).one()
    return row[0], row[1], row[2]


async def set_created_at(
    connection: AsyncConnection, booking: Booking, created_at: datetime
) -> None:
    await connection.execute(
        update(Booking).where(Booking.id == booking.id).values(created_at=created_at)
    )


def table_body(table: DiningTable) -> dict[str, Any]:
    return {"id": str(table.id), "label": table.label, "capacity": table.capacity}


async def test_staff_list_future_pending_requests_by_start_then_creation(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    pending = BookingStatus.PENDING
    later_created = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=EVENING,
        status=pending,
        party_size=6,
    )
    competitor = await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.six,
        starts_at=at(TOMORROW, 19, 30),
        status=pending,
        party_size=5,
    )
    earlier_created = await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.eight,
        starts_at=EVENING,
        status=pending,
        party_size=8,
    )
    await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.eight,
        starts_at=at(TODAY, 12),
        status=pending,
        party_size=8,
    )
    # Inside the auto-reject lead and exactly at it: approve refuses both, so the list hides them.
    for starts_at in (at(TODAY, 15), START + timedelta(minutes=120)):
        await add_booking(
            session_factory,
            user=users[GRACE],
            table=venue.eight,
            starts_at=starts_at,
            status=pending,
            party_size=8,
        )
    await add_booking(session_factory, user=users[ADA], table=venue.four, starts_at=EVENING)
    for status in (BookingStatus.CONFIRMED, BookingStatus.REJECTED, BookingStatus.CANCELLED):
        await add_booking(
            session_factory,
            user=users[ADA],
            table=venue.eight,
            starts_at=at(TOMORROW, 19, 30),
            status=status,
            party_size=6,
        )
    await set_created_at(connection, earlier_created, START - timedelta(hours=2))
    await set_created_at(connection, later_created, START - timedelta(hours=1))
    await set_created_at(connection, competitor, START - timedelta(minutes=30))
    await sign_in(client, STAFF)

    response = await client.get(REQUESTS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (3, 20, 0)
    assert [(item["id"], item["competing_requests"]) for item in body["items"]] == [
        (str(earlier_created.id), 0),
        (str(later_created.id), 1),
        (str(competitor.id), 1),
    ]
    assert body["items"][1] == {
        "id": str(later_created.id),
        "status": "PENDING",
        "owner_first_name": "Ada",
        "party_size": 6,
        "starts_at": EVENING.isoformat(),
        "ends_at": at(TOMORROW, 20, 30).isoformat(),
        "created_at": (START - timedelta(hours=1)).astimezone(EVENING.tzinfo).isoformat(),
        "table": table_body(venue.six),
        "location": location_body(venue.first),
        "competing_requests": 1,
    }
    page = await client.get(REQUESTS, params={"limit": 1, "offset": 1})
    assert page.status_code == 200, page.text
    assert [item["id"] for item in page.json()["items"]] == [str(later_created.id)]
    assert page.json()["total"] == 3
    assert (await client.get(REQUESTS, params={"limit": 51})).status_code == 422
    assert (await client.get(REQUESTS, params={"offset": 2**63})).status_code == 422


async def test_approving_confirms_the_request_and_rejects_its_competitors(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    approved = await request(client, venue.eight.id, EVENING, party_size=8)
    await sign_in(client, GRACE)
    competitor = await request(client, venue.eight.id, at(TOMORROW, 19, 30))
    other_table = await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.six,
        starts_at=EVENING,
        status=BookingStatus.PENDING,
        party_size=6,
    )
    adjacent = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.eight,
        starts_at=at(TOMORROW, 20, 30),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, approved, "approve")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONFIRMED"
    assert response.json()["competing_requests"] == 0
    assert await stored_decision(connection, approved) == (
        BookingStatus.CONFIRMED,
        START,
        staff.id,
    )
    assert await stored_decision(connection, competitor) == (
        BookingStatus.REJECTED,
        START,
        staff.id,
    )
    for untouched in (other_table, adjacent):
        assert await stored_decision(connection, untouched.id) == (
            BookingStatus.PENDING,
            None,
            None,
        )
    search = await client.get(
        SEARCH, params={"date": str(TOMORROW), "party_size": 8, "time": "19:00"}
    )
    assert search.status_code == 200, search.text
    assert search.json()["items"] == []
    await sign_in(client, ADA)
    owned = await client.get(BOOKINGS)
    assert owned.status_code == 200, owned.text
    assert {item["id"]: item["status"] for item in owned.json()}[approved] == "CONFIRMED"


async def test_approving_a_request_whose_table_was_taken_leaves_it_pending(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.six,
        starts_at=at(TOMORROW, 18, 30),
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, pending, "approve")

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert await stored_decision(connection, pending) == (BookingStatus.PENDING, None, None)


async def test_approve_maps_a_concurrent_exclusion_violation_to_slot_unavailable(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.six,
        starts_at=at(TOMORROW, 18, 30),
        party_size=6,
    )
    await sign_in(client, STAFF)

    async def no_overlap(*args: Any, **kwargs: Any) -> bool:
        return False

    # Simulates a parallel write that confirmed an overlap after this approve's check.
    monkeypatch.setattr(BookingRepository, "table_has_confirmed_overlap", no_overlap)
    response = await decide(client, pending, "approve")

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert await stored_decision(connection, pending) == (BookingStatus.PENDING, None, None)


@pytest.mark.parametrize(
    ("status", "table_name", "party_size"),
    [
        (BookingStatus.CONFIRMED, "six", 6),
        (BookingStatus.REJECTED, "six", 6),
        (BookingStatus.CANCELLED, "six", 6),
        (BookingStatus.CONFIRMED, "four", 2),
    ],
)
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_only_a_pending_request_can_be_decided(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    status: BookingStatus,
    table_name: str,
    party_size: int,
    action: str,
) -> None:
    booking = await add_booking(
        session_factory,
        user=users[ADA],
        table=getattr(venue, table_name),
        starts_at=EVENING,
        status=status,
        party_size=party_size,
    )
    await sign_in(client, STAFF)

    response = await decide(client, booking.id, action)

    assert_error(response, 409, "REQUEST_NOT_PENDING")
    assert await stored_decision(connection, booking.id) == (status, None, None)


async def test_a_request_whose_start_has_passed_cannot_be_approved(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=at(TODAY, 13),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, booking.id, "approve")

    assert_error(response, 409, "REQUEST_EXPIRED")
    assert await stored_decision(connection, booking.id) == (BookingStatus.PENDING, None, None)


@pytest.mark.parametrize(
    ("minutes_ahead", "expected_status"),
    [(90, 409), (120, 409), (121, 200)],
)
async def test_approval_closes_once_the_start_is_within_the_auto_reject_lead(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    minutes_ahead: int,
    expected_status: int,
) -> None:
    booking = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=START + timedelta(minutes=minutes_ahead),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, booking.id, "approve")

    if expected_status == 409:
        assert_error(response, 409, "REQUEST_EXPIRED")
        assert await stored_decision(connection, booking.id) == (
            BookingStatus.PENDING,
            None,
            None,
        )
    else:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "CONFIRMED"


async def test_staff_reject_a_pending_request_inside_the_auto_reject_lead(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.six,
        starts_at=START + timedelta(minutes=90),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, booking.id, "reject")

    assert response.status_code == 200, response.text
    assert await stored_decision(connection, booking.id) == (
        BookingStatus.REJECTED,
        START,
        staff.id,
    )


async def test_staff_reject_a_pending_request(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REJECTED"
    assert response.json()["id"] == pending
    assert await stored_decision(connection, pending) == (BookingStatus.REJECTED, START, staff.id)
    assert_error(await decide(client, pending, "reject"), 409, "REQUEST_NOT_PENDING")
    await sign_in(client, ADA)
    owned = await client.get(BOOKINGS)
    assert owned.status_code == 200, owned.text
    assert [(item["id"], item["status"]) for item in owned.json()] == [(pending, "REJECTED")]


async def test_staff_routes_refuse_other_users_and_anonymous_callers(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)

    assert_error(await client.get(REQUESTS), 403, "STAFF_ONLY")
    assert_error(await decide(client, pending, "approve"), 403, "STAFF_ONLY")
    assert_error(await decide(client, pending, "reject"), 403, "STAFF_ONLY")
    client.cookies.clear()
    assert_error(await client.get(REQUESTS), 401, "NOT_AUTHENTICATED")
    assert_error(await decide(client, pending, "approve"), 401, "NOT_AUTHENTICATED")
    assert_error(await decide(client, pending, "reject"), 401, "NOT_AUTHENTICATED")
    assert await stored_decision(connection, pending) == (BookingStatus.PENDING, None, None)


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_deciding_an_unknown_booking_is_not_found(
    client: httpx2.AsyncClient, staff: User, action: str
) -> None:
    await sign_in(client, STAFF)

    response = await decide(client, uuid.uuid4(), action)

    assert_error(response, 404, "BOOKING_NOT_FOUND")


async def test_the_owner_of_a_rejected_request_can_no_longer_change_or_share_it(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    link = await client.get(f"{BOOKINGS}/{pending}/invite")
    assert link.status_code == 200, link.text
    code = link.json()["code"]
    await sign_in(client, STAFF)
    assert (await decide(client, pending, "reject")).status_code == 200
    await sign_in(client, ADA)

    assert_error(await cancel(client, pending), 409, "BOOKING_REJECTED")
    assert_error(await edit(client, pending, at(TOMORROW, 20)), 409, "BOOKING_REJECTED")
    assert_error(
        await client.get(f"{BOOKINGS}/{pending}/slots", params={"duration_minutes": 90}),
        409,
        "BOOKING_REJECTED",
    )
    assert_error(await client.get(f"{BOOKINGS}/{pending}/invite"), 409, "BOOKING_REJECTED")
    await sign_in(client, GRACE)
    assert_error(await client.get(f"{INVITES}/{code}"), 409, "INVITE_CLOSED")
    assert_error(await client.post(f"{INVITES}/{code}/join"), 409, "INVITE_CLOSED")
    assert await stored_decision(connection, pending) == (BookingStatus.REJECTED, START, staff.id)


async def test_a_rejected_request_frees_the_owners_time(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], staff: User
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)
    assert (await decide(client, pending, "reject")).status_code == 200
    await sign_in(client, ADA)

    response = await book(client, venue.four.id, at(TOMORROW, 19, 30))

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "CONFIRMED"


async def test_the_owner_of_an_approved_request_can_pre_order(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dish = Dish(
        slug="test-steak",
        name="Test Steak",
        description="About test-steak",
        category=DishCategory.MAIN_COURSE,
        price_cents=2400,
        weight_grams=300,
        calories=450,
        protein="18g",
        fats="10g",
        carbs="40g",
        vitamins="A, C",
        is_available=True,
        popularity=0,
        prep_minutes=25,
        image_key="dishes/test-steak.webp",
        created_at=START,
    )
    async with session_factory() as session:
        session.add(dish)
        await session.commit()
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)
    assert (await decide(client, pending, "approve")).status_code == 200
    await sign_in(client, ADA)

    response = await client.put(f"{BOOKINGS}/{pending}/cart/items/{dish.id}", json={"quantity": 2})

    assert response.status_code == 200, response.text


async def test_an_approved_large_booking_cannot_be_edited(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)
    assert (await decide(client, pending, "approve")).status_code == 200
    await sign_in(client, ADA)

    assert_error(
        await edit(client, pending, at(TOMORROW, 19, 30), party_size=4),
        409,
        "LARGE_BOOKING_NOT_EDITABLE",
    )
    assert_error(
        await client.get(f"{BOOKINGS}/{pending}/slots", params={"duration_minutes": 90}),
        409,
        "LARGE_BOOKING_NOT_EDITABLE",
    )
    assert await stored_decision(connection, pending) == (
        BookingStatus.CONFIRMED,
        START,
        staff.id,
    )


async def test_the_owner_can_cancel_an_approved_large_booking(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    connection: AsyncConnection,
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)
    assert (await decide(client, pending, "approve")).status_code == 200
    await sign_in(client, ADA)

    response = await cancel(client, pending)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert (await stored_decision(connection, pending))[0] == BookingStatus.CANCELLED
