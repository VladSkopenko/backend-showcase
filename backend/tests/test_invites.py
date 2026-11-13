import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
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
    location_body,
    sign_in,
    stored_participants,
)
from support.http import set_cookies

from app.config.settings import BookingSettings, Settings, get_settings
from app.features.core.bookings.enums import ParticipantRole
from app.main import create_app
from app.model_registry import BookingParticipant, Guest, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

INVITES = "/api/v1/invites"
GUEST_TTL = timedelta(days=31)
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


async def invite_code(client: httpx2.AsyncClient, booking_id: str | uuid.UUID) -> str:
    response = await client.get(f"{BOOKINGS}/{booking_id}/invite")
    assert response.status_code == 200, response.text
    code: str = response.json()["code"]
    return code


async def open_booking(
    client: httpx2.AsyncClient,
    venue: Venue,
    *,
    starts_at: datetime = NOON,
    party_size: int = 2,
) -> tuple[dict[str, Any], str]:
    await sign_in(client, ADA)
    created = await book(client, venue.four.id, starts_at, party_size=party_size)
    assert created.status_code == 201, created.text
    code = await invite_code(client, created.json()["id"])
    client.cookies.clear()
    return created.json(), code


async def preview(client: httpx2.AsyncClient, code: str) -> httpx2.Response:
    return await client.get(f"{INVITES}/{code}")


async def join(
    client: httpx2.AsyncClient,
    code: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    if body is None:
        return await client.post(f"{INVITES}/{code}/join", headers=headers)
    return await client.post(f"{INVITES}/{code}/join", json=body, headers=headers)


async def join_as_new_guest(client: httpx2.AsyncClient, code: str, name: str) -> str:
    client.cookies.clear()
    response = await join(client, code, {"name": name})
    assert response.status_code == 200, response.text
    client.cookies.clear()
    return guest_token(response)


def guest_token(response: httpx2.Response) -> str:
    return set_cookies(response)["guest_token"]["value"]


def names(response: httpx2.Response) -> list[tuple[str, str]]:
    return [(p["name"], p["role"]) for p in response.json()["participants"]]


async def count_rows(connection: AsyncConnection, model: type[Any]) -> int:
    count = await connection.scalar(select(func.count()).select_from(model))
    assert count is not None
    return count


async def stored_guest(connection: AsyncConnection, token: str) -> tuple[str, datetime]:
    row = (
        await connection.execute(
            select(Guest.name, Guest.expires_at).where(
                Guest.token_hash == hashlib.sha256(token.encode()).hexdigest()
            )
        )
    ).one()
    return row[0], row[1]


async def test_the_owner_gets_the_same_invite_code_every_time(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    created = (await book(client, venue.four.id, at(TOMORROW, 12))).json()

    first = await client.get(f"{BOOKINGS}/{created['id']}/invite")
    second = await client.get(f"{BOOKINGS}/{created['id']}/invite")

    assert first.status_code == 200, first.text
    assert set(first.json()) == {"code"}
    assert len(first.json()["code"]) >= 22
    assert second.json() == first.json()


async def test_the_invite_link_is_refused_for_a_foreign_unknown_or_cancelled_booking(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)
    cancelled = (await book(client, venue.four.id, at(TOMORROW, 12))).json()
    assert (await cancel(client, cancelled["id"])).status_code == 200
    created = (await book(client, venue.four.id, at(TOMORROW, 18))).json()

    assert_error(
        await client.get(f"{BOOKINGS}/{cancelled['id']}/invite"), 409, "BOOKING_ALREADY_CANCELLED"
    )
    assert_error(await client.get(f"{BOOKINGS}/{uuid.uuid4()}/invite"), 404, "BOOKING_NOT_FOUND")
    await sign_in(client, GRACE)
    assert_error(await client.get(f"{BOOKINGS}/{created['id']}/invite"), 404, "BOOKING_NOT_FOUND")
    assert_error(await client.get(f"{BOOKINGS}/{cancelled['id']}/invite"), 404, "BOOKING_NOT_FOUND")
    client.cookies.clear()
    assert_error(await client.get(f"{BOOKINGS}/{cancelled['id']}/invite"), 401, "NOT_AUTHENTICATED")


async def test_a_joined_user_gets_no_invite_link(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    created, code = await open_booking(client, venue)
    await sign_in(client, GRACE)
    assert (await join(client, code)).status_code == 200

    response = await client.get(f"{BOOKINGS}/{created['id']}/invite")

    assert_error(response, 404, "BOOKING_NOT_FOUND")


async def test_the_preview_shows_the_booking_to_anyone_with_the_code(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    _, code = await open_booking(client, venue)

    response = await preview(client, code)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "owner_first_name": "Ada",
        "starts_at": "2026-11-13T12:00:00+04:00",
        "ends_at": "2026-11-13T13:30:00+04:00",
        "party_size": 2,
        "table": {"id": str(venue.four.id), "label": "Table 2", "capacity": 4},
        "location": location_body(venue.first),
    }


async def test_the_preview_is_refused_for_an_unknown_code_or_a_cancelled_booking(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    created, code = await open_booking(client, venue)
    assert_error(await preview(client, "unknown-code"), 404, "INVITE_NOT_FOUND")
    await sign_in(client, ADA)
    assert (await cancel(client, created["id"])).status_code == 200
    client.cookies.clear()

    assert_error(await preview(client, code), 409, "INVITE_CLOSED")


@pytest.mark.parametrize(("minutes", "status_code"), [(20, 200), (21, 409)])
async def test_preview_and_join_close_at_the_preorder_lock(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    minutes: int,
    status_code: int,
) -> None:
    created, code = await open_booking(client, venue, starts_at=at(TODAY, 14))
    fake_clock.advance(minutes=minutes)

    previewed = await preview(client, code)
    joined = await join(client, code, {"name": "Alex"})

    assert previewed.status_code == status_code, previewed.text
    assert joined.status_code == status_code, joined.text
    if status_code == 409:
        assert previewed.json()["code"] == "INVITE_CLOSED"
        assert joined.json()["code"] == "INVITE_CLOSED"
        assert await count_rows(connection, Guest) == 0
        assert len(await stored_participants(connection, created["id"])) == 1


async def test_a_guest_joins_by_name_and_reads_the_booking_with_the_cookie(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    created, code = await open_booking(client, venue)

    response = await join(client, code, {"name": "  Alex  "})

    assert response.status_code == 200, response.text
    body = response.json()
    owner, guest = body["participants"]
    assert body == {
        **created,
        "role": "GUEST",
        "participant_id": guest["id"],
        "participants": [owner, {"id": guest["id"], "name": "Alex", "role": "GUEST"}],
    }
    assert owner == created["participants"][0]
    cookie = set_cookies(response)["guest_token"]
    assert cookie["path"] == "/"
    assert cookie["max-age"] == str(31 * 24 * 60 * 60)
    assert {"httponly", "secure"} <= set(cookie)
    assert cookie["samesite"].lower() == "lax"
    assert await stored_guest(connection, cookie["value"]) == ("Alex", START + GUEST_TTL)
    client.cookies.clear()
    read = await client.get(f"{BOOKINGS}/{created['id']}", headers=as_guest(cookie["value"]))
    assert read.status_code == 200, read.text
    assert read.json() == body
    await sign_in(client, ADA)
    assert (await client.get(BOOKINGS)).json() == [
        {**body, "role": "OWNER", "participant_id": owner["id"]}
    ]


@pytest.mark.parametrize("body", [None, {}, {"name": None}, {"name": ""}, {"name": "   "}])
async def test_a_guest_without_a_name_is_refused(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    body: dict[str, Any] | None,
) -> None:
    created, code = await open_booking(client, venue)

    response = await join(client, code, body)

    assert_error(response, 400, "GUEST_NAME_REQUIRED")
    assert "set-cookie" not in response.headers
    assert await count_rows(connection, Guest) == 0
    assert len(await stored_participants(connection, created["id"])) == 1


@pytest.mark.parametrize(("name", "status_code"), [("A" * 50, 200), ("A" * 51, 422)])
async def test_a_guest_name_has_at_most_fifty_characters(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    name: str,
    status_code: int,
) -> None:
    _, code = await open_booking(client, venue)

    response = await join(client, code, {"name": name})

    assert response.status_code == status_code, response.text
    if status_code == 422:
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert await count_rows(connection, Guest) == 0


async def test_a_signed_in_user_joins_with_the_profile_name_and_no_guest_cookie(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    created, code = await open_booking(client, venue)
    await sign_in(client, GRACE)
    assert (await book(client, venue.other.id, at(TOMORROW, 12))).status_code == 201

    response = await join(client, code, {"name": "Someone Else"})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "GUEST"
    assert names(response) == [("Ada", "OWNER"), ("Grace", "GUEST")]
    assert response.json()["participant_id"] == response.json()["participants"][1]["id"]
    assert "guest_token" not in set_cookies(response)
    assert await count_rows(connection, Guest) == 0
    assert await stored_participants(connection, created["id"]) == [
        (users[ADA].id, None, ParticipantRole.OWNER),
        (users[GRACE].id, None, ParticipantRole.GUEST),
    ]
    listed = (await client.get(BOOKINGS)).json()
    assert {booking["id"]: booking["role"] for booking in listed}[created["id"]] == "GUEST"
    assert_error(await edit(client, created["id"], at(TOMORROW, 14)), 404, "BOOKING_NOT_FOUND")
    assert_error(await cancel(client, created["id"]), 404, "BOOKING_NOT_FOUND")


async def test_a_signed_in_user_with_a_guest_cookie_joins_as_the_user(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    _, code = await open_booking(client, venue, party_size=3)
    token = await join_as_new_guest(client, code, "Alex")
    fake_clock.advance(minutes=1)
    await sign_in(client, GRACE)
    access_token = client.cookies["access_token"]
    client.cookies.clear()

    response = await join(
        client, code, headers={"Cookie": f"access_token={access_token}; guest_token={token}"}
    )

    assert response.status_code == 200, response.text
    assert names(response) == [("Ada", "OWNER"), ("Alex", "GUEST"), ("Grace", "GUEST")]
    assert "set-cookie" not in response.headers
    assert await stored_guest(connection, token) == ("Alex", START + GUEST_TTL)


@pytest.mark.parametrize("joiner", ["owner", "user", "guest"])
async def test_joining_again_changes_nothing(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
    joiner: str,
) -> None:
    created, code = await open_booking(client, venue, party_size=3)
    token = await join_as_new_guest(client, code, "Alex")
    fake_clock.advance(minutes=1)
    await sign_in(client, GRACE)
    assert (await join(client, code)).status_code == 200
    before = await stored_participants(connection, created["id"])
    fake_clock.advance(hours=1)
    headers = None
    if joiner == "guest":
        client.cookies.clear()
        headers = as_guest(token)
    else:
        await sign_in(client, ADA if joiner == "owner" else GRACE)

    response = await join(client, code, {"name": "Other"}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["role"] == ("OWNER" if joiner == "owner" else "GUEST")
    assert names(response) == [("Ada", "OWNER"), ("Alex", "GUEST"), ("Grace", "GUEST")]
    position = {"owner": 0, "guest": 1, "user": 2}[joiner]
    assert response.json()["participant_id"] == response.json()["participants"][position]["id"]
    assert "set-cookie" not in response.headers
    assert await stored_participants(connection, created["id"]) == before
    assert await stored_guest(connection, token) == ("Alex", START + GUEST_TTL)


async def test_a_guest_joins_a_second_booking_with_the_same_identity(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    first, first_code = await open_booking(client, venue)
    second, second_code = await open_booking(client, venue, starts_at=at(TOMORROW, 18))
    token = await join_as_new_guest(client, first_code, "Alex")
    fake_clock.advance(hours=1)

    response = await join(client, second_code, {"name": "Other"}, headers=as_guest(token))

    assert response.status_code == 200, response.text
    assert names(response) == [("Ada", "OWNER"), ("Alex", "GUEST")]
    assert guest_token(response) == token
    assert await count_rows(connection, Guest) == 1
    assert await stored_guest(connection, token) == (
        "Alex",
        START + timedelta(hours=1) + GUEST_TTL,
    )
    for booking in (first, second):
        read = await client.get(f"{BOOKINGS}/{booking['id']}", headers=as_guest(token))
        assert read.status_code == 200, read.text
        assert read.json()["role"] == "GUEST"


async def test_a_guest_with_a_valid_cookie_joins_another_booking_without_a_body(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    _, first_code = await open_booking(client, venue)
    _, second_code = await open_booking(client, venue, starts_at=at(TOMORROW, 18))
    token = await join_as_new_guest(client, first_code, "Alex")
    fake_clock.advance(hours=1)

    response = await join(client, second_code, headers=as_guest(token))

    assert response.status_code == 200, response.text
    assert names(response) == [("Ada", "OWNER"), ("Alex", "GUEST")]
    assert guest_token(response) == token
    assert await stored_guest(connection, token) == (
        "Alex",
        START + timedelta(hours=1) + GUEST_TTL,
    )


@pytest.mark.parametrize(("minutes", "status_code"), [(5, 200), (6, 409)])
async def test_join_follows_the_preorder_lock_and_guest_cookie_settings(
    client: httpx2.AsyncClient,
    app: FastAPI,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    minutes: int,
    status_code: int,
) -> None:
    settings = Settings(
        booking=BookingSettings(
            preorder_lock_minutes=45, guest_token_ttl_days=7, guest_cookie_path="/api/v1"
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    _, code = await open_booking(client, venue, starts_at=at(TODAY, 14))
    fake_clock.advance(minutes=minutes)

    response = await join(client, code, {"name": "Alex"})

    assert response.status_code == status_code, response.text
    if status_code == 409:
        assert response.json()["code"] == "INVITE_CLOSED"
        assert await count_rows(connection, Guest) == 0
    else:
        cookie = set_cookies(response)["guest_token"]
        assert cookie["path"] == "/api/v1"
        assert cookie["max-age"] == str(7 * 24 * 60 * 60)
        assert await stored_guest(connection, cookie["value"]) == (
            "Alex",
            START + timedelta(minutes=minutes) + timedelta(days=7),
        )


async def test_an_expired_guest_cookie_counts_as_no_guest(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    fake_clock: FakeClock,
) -> None:
    _, first_code = await open_booking(client, venue)
    token = await join_as_new_guest(client, first_code, "Alex")
    fake_clock.advance(days=31)
    later = await add_booking(
        session_factory,
        user=users[ADA],
        table=venue.four,
        starts_at=at(TODAY + timedelta(days=32), 12),
    )
    await sign_in(client, ADA)
    later_code = await invite_code(client, later.id)
    client.cookies.clear()

    nameless = await join(client, later_code, headers=as_guest(token))
    named = await join(client, later_code, {"name": "Alex"}, headers=as_guest(token))

    assert_error(nameless, 400, "GUEST_NAME_REQUIRED")
    assert named.status_code == 200, named.text
    assert guest_token(named) != token
    assert await count_rows(connection, Guest) == 2


async def test_a_full_booking_takes_nobody_else(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    created, code = await open_booking(client, venue)
    await join_as_new_guest(client, code, "Alex")

    anonymous = await join(client, code, {"name": "Bea"})
    await sign_in(client, GRACE)
    signed_in = await join(client, code)

    assert_error(anonymous, 409, "BOOKING_FULL")
    assert_error(signed_in, 409, "BOOKING_FULL")
    assert await count_rows(connection, Guest) == 1
    assert len(await stored_participants(connection, created["id"])) == 2


async def test_participants_are_listed_owner_first_then_by_join_time(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], fake_clock: FakeClock
) -> None:
    _, code = await open_booking(client, venue, party_size=4)
    fake_clock.advance(minutes=1)
    await join_as_new_guest(client, code, "Alex")
    fake_clock.advance(minutes=1)
    await sign_in(client, GRACE)
    assert (await join(client, code)).status_code == 200
    fake_clock.advance(minutes=1)

    client.cookies.clear()
    response = await join(client, code, {"name": "Bea"})

    assert names(response) == [
        ("Ada", "OWNER"),
        ("Alex", "GUEST"),
        ("Grace", "GUEST"),
        ("Bea", "GUEST"),
    ]


async def test_join_is_closed_for_a_cancelled_booking_or_an_unknown_code(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User], connection: AsyncConnection
) -> None:
    created, code = await open_booking(client, venue)
    assert_error(await join(client, "unknown-code", {"name": "Alex"}), 404, "INVITE_NOT_FOUND")
    await sign_in(client, ADA)
    assert (await cancel(client, created["id"])).status_code == 200
    client.cookies.clear()

    response = await join(client, code, {"name": "Alex"})

    assert_error(response, 409, "INVITE_CLOSED")
    assert await count_rows(connection, Guest) == 0
    assert await count_rows(connection, BookingParticipant) == 1


async def test_join_reports_the_first_failing_check(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    cancelled, cancelled_code = await open_booking(client, venue, starts_at=at(TOMORROW, 18))
    _, code = await open_booking(client, venue)
    await sign_in(client, ADA)
    assert (await cancel(client, cancelled["id"])).status_code == 200
    client.cookies.clear()
    bad_access = {"Cookie": "access_token=not-a-token"}

    assert_error(await join(client, "unknown-code", headers=bad_access), 401, "NOT_AUTHENTICATED")
    assert_error(await join(client, "unknown-code"), 404, "INVITE_NOT_FOUND")
    assert_error(await join(client, cancelled_code), 409, "INVITE_CLOSED")
    await sign_in(client, ADA)
    assert_error(await join(client, cancelled_code), 409, "INVITE_CLOSED")
    assert (await join(client, code)).status_code == 200
    token = await join_as_new_guest(client, code, "Alex")
    assert (await join(client, code, headers=as_guest(token))).status_code == 200
    assert_error(await join(client, code), 400, "GUEST_NAME_REQUIRED")
    assert_error(await join(client, code, {"name": "Bea"}), 409, "BOOKING_FULL")
    await sign_in(client, ADA)
    assert (await join(client, code)).status_code == 200


async def test_preview_reports_the_first_failing_check(
    client: httpx2.AsyncClient, venue: Venue, users: dict[str, User]
) -> None:
    cancelled, cancelled_code = await open_booking(client, venue)
    await sign_in(client, ADA)
    assert (await cancel(client, cancelled["id"])).status_code == 200
    client.cookies.clear()

    assert_error(await preview(client, "unknown-code"), 404, "INVITE_NOT_FOUND")
    assert_error(await preview(client, cancelled_code), 409, "INVITE_CLOSED")
